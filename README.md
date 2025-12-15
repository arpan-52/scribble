# scribble

Scalable, browser-based GUI for interactive exploration and plotting of CASA Measurement Set (MS) files.

- Handles millions or billions of points with Datashader.
- GUI: Pick axis, groupings, filters, *and correlations* for visibilities.
- Only unflagged data is plotted.
- Plot export as PNG.

## Quick Start

1. Install [python-casacore](https://github.com/casacore/python-casacore) (Linux recommended):

    ```sh
    sudo apt-get install python3-pip libcasa-casa-dev libcasa-tables-dev
    pip install python-casacore
    ```

2. Install scribble:

    ```sh
    pip install .
    ```

3. Run:

    ```sh
    scribble
    ```

4. In the browser, select your `.ms` directory and plot!

## Features

- MS file browser and selection panel
- All columns selectable for axes or groupings
- (For DATA, CORRECTED_DATA, etc.) correlation selector
- Filtering options for all columns
- Excludes flagged data (only plots unflagged)
- PNG export

## License

MIT License.