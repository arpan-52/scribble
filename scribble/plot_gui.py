import os
import threading
from casacore.tables import table
import pandas as pd
import numpy as np
from bokeh.io import show
from bokeh.layouts import row, column
from bokeh.models import Button, Select, MultiSelect, ColumnDataSource, Div, FileInput
from bokeh.plotting import figure
import datashader as ds
import datashader.transfer_functions as tf
from bokeh.server.server import Server

VIS_COLUMNS = ["DATA", "CORRECTED_DATA", "MODEL_DATA", "RESIDUAL_DATA"]

def list_possible_ms_dirs(path='.'):
    """List subdirectories that look like Measurement Set files."""
    candidates = []
    for f in os.listdir(path):
        fpath = os.path.join(path, f)
        if os.path.isdir(fpath) and os.path.exists(os.path.join(fpath, 'TABLES')):
            candidates.append(f)
    return candidates

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
        # If 3D, need to pick corr axis too
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
    # State for MS file selection
    selected_ms = {'path': None}

    file_div = Div(text="<b>Select a Measurement Set (.ms directory):</b>")
    ms_select = Select(title="MS Directory", options=list_possible_ms_dirs('.'), value=None)
    reload_btn = Button(label="Refresh List", button_type="default")

    axis_opts = []
    vis_colinfo = {}
    flag_col = None
    select_x = Select(title="X Axis", options=[], value=None)
    select_y = Select(title="Y Axis", options=[], value=None)
    select_group = Select(title="Group by", options=["None"], value="None")
    select_corr = MultiSelect(title="Correlation(s)", options=[], value=[], visible=False)
    filter_div = Div(text=f"<b>Flag filtering enabled by default (only unflagged visibilities plotted).</b>")
    plot_button = Button(label="Plot", button_type="success", disabled=True)
    export_button = Button(label="Export as PNG", button_type="primary", disabled=True)
    status_div = Div(text="")
    outfig = figure(width=800, height=450, title="Scribble Plot", tools="pan,wheel_zoom,box_zoom,reset,save")
    render = outfig.image_rgba([], x=[], y=[], dw=[], dh=[])

    def update_ms_list():
        ms_select.options = list_possible_ms_dirs('.')
        ms_select.value = None
        axis_opts.clear()
        vis_colinfo.clear()
        select_x.options = []
        select_y.options = []
        select_group.options = ["None"]
        select_corr.options = []
        plot_button.disabled = True
        export_button.disabled = True
        status_div.text = ""
        outfig.title.text = "Scribble Plot"
        render.data_source.data = dict(image=[], x=[], y=[], dw=[], dh=[])

    def ms_chosen(attr, old, new):
        ms_path = ms_select.value
        if ms_path:
            ms_path = os.path.abspath(ms_path)
            selected_ms['path'] = ms_path
            colnames, visinfo = load_ms_columns(ms_path)
            axis_opts[:] = [c for c in colnames if c != 'FLAG']
            vis_colinfo.clear()
            vis_colinfo.update(visinfo)
            select_x.options = axis_opts
            select_x.value = axis_opts[0]
            select_y.options = axis_opts
            select_y.value = axis_opts[1]
            select_group.options = ["None"] + axis_opts
            select_group.value = "None"
            # Is a vis column present?
            update_corr_visibility()
            plot_button.disabled = False
            export_button.disabled = False
            # Find flag col
            global flag_col
            flag_col = 'FLAG' if 'FLAG' in colnames else None

    def update_corr_visibility(*args):
        inx = select_x.value in vis_colinfo
        iny = select_y.value in vis_colinfo
        any_vis = inx or iny
        select_corr.visible = any_vis
        if any_vis:
            # Use whichever is picked for axis
            viscol = select_x.value if inx else select_y.value
            corr_labels = get_corr_labels(selected_ms['path'], viscol)
            select_corr.options = corr_labels
            if not select_corr.value or set(select_corr.value) - set(corr_labels):
                select_corr.value = [corr_labels[0]]
        else:
            select_corr.options = []
            select_corr.value = []

    def run_plot():
        ms_path = selected_ms['path']
        if not ms_path:
            status_div.text = "No Measurement Set selected!"
            return
        xcol, ycol = select_x.value, select_y.value
        groupcol = select_group.value if select_group.value != "None" else None
        usecorr = select_corr.value if select_corr.visible else None
        corr_idx = None
        if usecorr and select_corr.visible:
            corr_labels = select_corr.options
            corr_idx = corr_labels.index(usecorr[0])
        usecols = set([xcol, ycol])
        if groupcol: usecols.add(groupcol)
        if flag_col: usecols.add(flag_col)
        for v in VIS_COLUMNS:
            if xcol == v or ycol == v:
                usecols.add(v)
        df = load_ms_data(ms_path, list(usecols), corr_idx=corr_idx, flag_col=flag_col)
        if df.empty:
            status_div.text = "No data to plot (possible all flagged/filtered?)"
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
        status_div.text = f"Plotted {len(df)} points."

    def export_png():
        from bokeh.io.export import export_png
        export_png(outfig, filename="scribble_export.png")
        status_div.text = "Plot exported to scribble_export.png"

    reload_btn.on_click(update_ms_list)
    ms_select.on_change("value", ms_chosen)
    select_x.on_change("value", lambda *args: update_corr_visibility())
    select_y.on_change("value", lambda *args: update_corr_visibility())
    plot_button.on_click(run_plot)
    export_button.on_click(export_png)

    update_ms_list()
    layout = column(
        row(file_div, ms_select, reload_btn),
        row(select_x, select_y, select_group, select_corr),
        filter_div,
        row(plot_button, export_button),
        status_div,
        outfig
    )
    doc.add_root(layout)
    doc.title = "scribble: Measurement Set Plotter"

def plot_gui(ms_path=None):
    def bk_worker():
        # If given MS path, immediately load that
        def app_wrapper(doc):
            if ms_path:
                # Pre-populate path selection and skip file picker
                selected_ms = {'path': ms_path}
                bokeh_app(doc)
            else:
                bokeh_app(doc)
        server = Server(
            {'/': app_wrapper},
            port=0, allow_websocket_origin=["localhost:.*", "127.0.0.1:.*"]
        )
        server.start()
        import webbrowser
        url = f"http://localhost:{server.port}/"
        webbrowser.open(url)
        server.io_loop.start()
    threading.Thread(target=bk_worker, daemon=True).start()
