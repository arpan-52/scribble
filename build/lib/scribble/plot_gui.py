import os
import threading
from casacore.tables import table
import pandas as pd
import numpy as np
from bokeh.layouts import row, column
from bokeh.models import Button, Select, MultiSelect, Div, TextInput
from bokeh.plotting import figure
import datashader as ds
import datashader.transfer_functions as tf

VIS_COLUMNS = ["DATA", "CORRECTED_DATA", "MODEL_DATA", "RESIDUAL_DATA"]

def load_ms_columns(ms_path):
    t = table(ms_path)
    colnames = t.colnames()
    desc = t.coldesc()
    vis_colinfo = {}
    for c in VIS_COLUMNS:
        if c in colnames:
            shape = desc[c].get('shape', [])
            n_corr = shape[-1] if len(shape) >= 1 else 1
            n_chan = shape[-2] if len(shape) >= 2 else 1
            vis_colinfo[c] = {"shape": shape, "n_corr": n_corr, "n_chan": n_chan}
    t.close()
    return colnames, vis_colinfo

def load_ms_data(ms_path, usecols, corr_idx=None, flag_col=None):
    t = table(ms_path)
    arrs = {}
    for c in usecols:
        if c in VIS_COLUMNS:  # Vis column with correlation axis
            data = t.getcol(c)
            if data.ndim == 3 and corr_idx is not None:
                data = data[:, :, corr_idx]
            arrs[c] = data.flatten()
        else:
            data = t.getcol(c)
            if np.ndim(data) > 1:
                data = data.flatten()
            arrs[c] = data
    # Apply flag masking
    if flag_col and flag_col in t.colnames():
        flags = t.getcol(flag_col)
        if flags.ndim == 3 and corr_idx is not None:
            flags = flags[:, :, corr_idx]
        mask = ~flags.flatten()
        for k in arrs.keys():
            arrs[k] = arrs[k][mask]
    t.close()
    return pd.DataFrame(arrs)

def get_corr_labels(ms_path, vis_col):
    pol_path = os.path.join(ms_path, "POLARIZATION")
    t = None
    try:
        t = table(pol_path)
        corr_types = t.getcol("CORR_TYPE")[0]   # shape: (n_corr,)
        CORR_MAP = {5: "RR", 6: "RL", 7: "LR", 8: "LL",
                    9: "XX", 10: "XY", 11: "YX", 12: "YY"}
        corr_names = [CORR_MAP.get(c, str(c)) for c in corr_types]
    except Exception:
        # fallback: 0, 1, 2, ...
        colnames, vis_colinfo = load_ms_columns(ms_path)
        n_corr = vis_colinfo.get(vis_col, {}).get('n_corr', 4)
        corr_names = [str(i) for i in range(n_corr)]
    finally:
        if t: t.close()
    return corr_names

def bokeh_app(doc):
    # Initial GUI: file input and status only
    info_div = Div(text="<b>Enter/paste full path to your Measurement Set (.ms directory), then click Load.</b>")
    ms_path_input = TextInput(title="MS Directory", value="", width=500)
    load_btn = Button(label="Load MS", button_type="success", disabled=False)
    status_div = Div(text="", width=600)
    controls_div = Div()
    plot_layout = column()
    doc.add_root(column(
        info_div,
        row(ms_path_input, load_btn),
        status_div,
        plot_layout  # Populated after an MS is loaded
    ))
    doc.title = "scribble: Measurement Set Plotter"

    # --- Loading logic ---
    def on_load():
        path = ms_path_input.value.strip()
        if not path or not os.path.isdir(path) or not os.path.exists(os.path.join(path, 'TABLES')):
            status_div.text = "<span style='color:red;'>Not a valid MS directory path!</span>"
            plot_layout.children = []
            return

        status_div.text = f"<b style='color:green;'>Loaded: {os.path.abspath(path)}</b>"

        # Build dynamic selectors and plot controls
        colnames, vis_colinfo = load_ms_columns(path)
        axis_opts = [c for c in colnames if c != 'FLAG']
        flag_col = 'FLAG' if 'FLAG' in colnames else None
        vis_columns_avail = [c for c in VIS_COLUMNS if c in colnames]

        select_x = Select(title="X Axis", options=axis_opts, value=axis_opts[0])
        select_y = Select(title="Y Axis", options=axis_opts, value=axis_opts[1])
        select_group = Select(title="Group by", options=["None"]+axis_opts, value="None")
        select_corr = MultiSelect(title="Correlation(s)", options=[], value=[], visible=False)
        filter_div = Div(text=f"<b>Flag filtering enabled: only unflagged visibilities plotted.</b>")
        plot_button = Button(label="Plot", button_type="success")
        export_button = Button(label="Export as PNG", button_type="primary", disabled=True)
        plot_status = Div(text="")
        outfig = figure(width=800, height=450, title="Scribble Plot", 
                        tools="pan,wheel_zoom,box_zoom,reset,save")
        render = outfig.image_rgba([], x=[], y=[], dw=[], dh=[])

        def update_corr_visibility(*args):
            xval, yval = select_x.value, select_y.value
            inx = xval in vis_columns_avail
            iny = yval in vis_columns_avail
            any_vis = inx or iny
            select_corr.visible = any_vis
            if any_vis:
                viscol = xval if inx else yval
                corr_labels = get_corr_labels(path, viscol)
                select_corr.options = corr_labels
                if not select_corr.value or set(select_corr.value) - set(corr_labels):
                    select_corr.value = [corr_labels[0]]
            else:
                select_corr.options = []
                select_corr.value = []

        select_x.on_change("value", update_corr_visibility)
        select_y.on_change("value", update_corr_visibility)

        def run_plot():
            xcol = select_x.value
            ycol = select_y.value
            groupcol = select_group.value if select_group.value != "None" else None
            usecorr = select_corr.value if select_corr.visible else None
            corr_idx = None
            if usecorr and select_corr.visible:
                corr_labels = select_corr.options
                corr_idx = corr_labels.index(usecorr[0])
            usecols = set([xcol, ycol])
            if groupcol: usecols.add(groupcol)
            if flag_col: usecols.add(flag_col)
            for v in vis_columns_avail:
                if xcol == v or ycol == v:
                    usecols.add(v)
            try:
                df = load_ms_data(path, list(usecols), corr_idx=corr_idx, flag_col=flag_col)
            except Exception as e:
                plot_status.text = f"<span style='color:red;'>Error loading MS data: {e}</span>"
                return
            if df.empty:
                plot_status.text = "<span style='color:red;'>No data to plot (all flagged?)</span>"
                return
            cvs = ds.Canvas(plot_width=800, plot_height=450)
            agg = cvs.points(df, xcol, ycol)
            img = tf.shade(agg, cmap="fire", how="linear").to_pil()
            arr = np.array(img.convert("RGBA"))
            arr = np.flipud(arr)
            buf = np.dstack([arr[:,:,i] for i in range(4)]).view(np.uint32)[...,0]
            render.data_source.data = dict(
                image=[buf],
                x=[df[xcol].min()],
                y=[df[ycol].min()],
                dw=[df[xcol].max()-df[xcol].min()],
                dh=[df[ycol].max()-df[ycol].min()],
            )
            outfig.title.text = f"{xcol} vs {ycol}" + (f" ({usecorr[0]})" if usecorr else "")
            plot_status.text = f"Plotted {len(df)} points."
            export_button.disabled = False

        plot_button.on_click(run_plot)

        def export_png():
            from bokeh.io.export import export_png
            export_png(outfig, filename="scribble_export.png")
            plot_status.text = "Plot exported to scribble_export.png"
        export_button.on_click(export_png)
        export_button.disabled = True

        update_corr_visibility()

        plot_controls = column(
            row(select_x, select_y, select_group, select_corr),
            filter_div,
            row(plot_button, export_button),
            plot_status,
            outfig
        )
        plot_layout.children = [plot_controls]

    load_btn.on_click(on_load)
    

def plot_gui(ms_path=None):
    def bk_worker():
        import socket
        from bokeh.server.server import Server
        def app_wrapper(doc):
            bokeh_app(doc)
        # Find open port
        sock = socket.socket(); sock.bind(('', 0)); port = sock.getsockname()[1]; sock.close()
        allowed_origins = [f"localhost:{port}", f"127.0.0.1:{port}"]
        server = Server(
            {'/': app_wrapper},
            port=port, allow_websocket_origin=allowed_origins
        )
        server.start()
        import webbrowser
        url = f"http://localhost:{server.port}/"
        webbrowser.open(url)
        server.io_loop.start()
    threading.Thread(target=bk_worker, daemon=True).start()