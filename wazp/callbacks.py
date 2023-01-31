import base64
import pathlib as pl
import re

import dash
import dash_bootstrap_components as dbc
import utils
import yaml
from dash import Input, Output, State, html

VIDEO_TYPES = [".avi", ".mp4"]
# TODO: other video extensions? have this in project config file instead?


def get_metadata_callbacks(app: dash.Dash) -> None:
    """
    Return all metadata callback functions

    """

    @app.callback(
        Output("output-data-upload", "children"),
        Input("upload-data", "contents"),
        State("upload-data", "filename"),
    )
    def update_file_drop_output(up_content: str, up_filename: str) -> html.Div:
        """
        Read uploaded config file and return component with:
        - table with metadata per video,
        - auxiliary buttons for common table manipulations

        """
        # Read uploaded content
        if up_content is not None:
            _, content_str = up_content.split(",")
            try:
                if "yaml" in up_filename:
                    # get config
                    cfg = yaml.safe_load(base64.b64decode(content_str))
                    # get video dir
                    video_dir = cfg["videos_dir_path"]
                    # get metadata fields dict
                    with open(cfg["metadata_fields_file_path"]) as mdf:
                        metadata_fields_dict = yaml.safe_load(mdf)
            except Exception as e:
                print(e)
                return html.Div(["There was an error processing this file."])

            # Define component layout
            return html.Div(
                [
                    # metadata table
                    utils.metadata_table_component_from_df(
                        utils.df_from_metadata_yaml_files(
                            video_dir, metadata_fields_dict
                        )
                    ),
                    # auxiliary buttons
                    html.Div(
                        [
                            html.Button(
                                children="Check for missing metadata files",
                                id="add-rows-for-missing-button",
                                n_clicks=0,
                                style={"margin-right": "10px"},
                            ),
                            html.Button(
                                children="Add empty row",
                                id="add-row-manually-button",
                                n_clicks=0,
                                style={"margin-right": "10px"},
                            ),
                            html.Button(
                                children="Select/unselect all rows",
                                id="select-all-rows-button",
                                n_clicks=0,
                                style={"margin-right": "10px"},
                            ),
                            html.Button(
                                children="Export selected rows as yaml",
                                id="export-selected-rows-button",
                                n_clicks=0,
                                style={"margin-right": "10px"},
                            ),
                            dbc.Alert(
                                children="",
                                id="alert",
                                dismissable=True,
                                fade=False,
                                is_open=False,
                            ),
                        ]
                    ),
                ]
            )

    @app.callback(
        Output("metadata-table", "data"),
        Output("add-row-manually-button", "n_clicks"),
        Output("add-rows-for-missing-button", "n_clicks"),
        Input("add-row-manually-button", "n_clicks"),
        Input("add-rows-for-missing-button", "n_clicks"),
        State("metadata-table", "data"),
        State("metadata-table", "columns"),
        State("upload-data", "contents"),
    )
    def add_rows(
        n_clicks_add_row_manually: int,
        n_clicks_add_rows_missing: int,
        table_rows: list[dict],
        table_columns: list[dict],
        up_content: str,
    ) -> tuple[list[dict], int, int]:
        """
        Add rows to metadata table, either:
        - manually
        - based on videos with missing yaml files

        Both are triggered by clicking the corresponding buttons

        """

        # Add empty rows manually
        if n_clicks_add_row_manually > 0 and table_columns:
            table_rows.append({c["id"]: "" for c in table_columns})
            n_clicks_add_row_manually = 0  # reset clicks

        # Add rows for videos w/ missing metadata
        if n_clicks_add_rows_missing > 0 and table_columns:
            # Read config for videos directory
            _, content_str = up_content.split(",")
            cfg = yaml.safe_load(base64.b64decode(content_str))
            video_dir = cfg["videos_dir_path"]

            # List of files currently shown in table
            list_files_in_tbl = [
                d[cfg["metadata_key_field_str"]] for d in table_rows
            ]

            # List of videos w/o metadata and not in table
            list_video_files = []
            list_metadata_files = []
            for f in pl.Path(video_dir).iterdir():
                if str(f).endswith("metadata.yaml"):
                    list_metadata_files.append(
                        re.sub(".metadata$", "", f.stem)
                    )
                elif any(v in str(f) for v in VIDEO_TYPES):
                    list_video_files.append(f)  # list of PosixPaths
            list_videos_wo_metadata = [
                f.name
                for f in list_video_files
                if (f.stem not in list_metadata_files)
                and (f.name not in list_files_in_tbl)
            ]

            # Add a row for every video w/o metadata
            for vid in list_videos_wo_metadata:
                table_rows.append(
                    {
                        c["id"]: vid if c["id"] == "File" else ""
                        for c in table_columns
                    }
                )
                n_clicks_add_rows_missing = 0  # reset clicks

            # If the original table had only one empty row: pop it
            # (it occurs if initially there are no yaml files)
            # TODO: this is a bit hacky maybe? is there a better way?
            if list_files_in_tbl == [""]:
                table_rows = table_rows[1:]

        return table_rows, n_clicks_add_row_manually, n_clicks_add_rows_missing

    @app.callback(
        Output("metadata-table", "selected_rows"),
        Output("select-all-rows-button", "n_clicks"),
        Output("export-selected-rows-button", "n_clicks"),
        Output("alert", "is_open"),
        Output("alert", "children"),
        Input("select-all-rows-button", "n_clicks"),
        Input("export-selected-rows-button", "n_clicks"),
        Input("metadata-table", "data_previous"),
        State("metadata-table", "data"),
        State(
            "metadata-table", "derived_viewport_data"
        ),  # data on the current page
        State("metadata-table", "selected_rows"),
        State("upload-data", "contents"),
        State("upload-data", "filename"),
        State("alert", "is_open"),
    )
    def modify_rows_selection(
        n_clicks_select_all: int,
        n_clicks_export: int,
        data_previous: list,
        data: list[dict],
        data_page: list[dict],
        list_selected_rows: list[int],
        up_content: str,
        up_filename: str,
        alert_state: bool,
    ) -> tuple[list[int], int, int, bool, str]:
        """
        Modify the set of rows that are selected.

        A row's checkbox is modified if:
        - the user edits the data on that row (checkbox set to True)
        - the export button is clicked (checkbox set to False after exporting)
        - the 'select/unselect' all button is clicked
        """

        # Initialise alert message w empty
        alert_message = ""

        # If there is an edit to the row data: set checkbox to True
        if data_previous is not None:
            list_selected_rows = utils.set_edited_row_checkbox_to_true(
                data_previous,
                data,
                list_selected_rows,
            )

        # If the export button is clicked: export selected rows and unselect
        if (n_clicks_export > 0) and list_selected_rows:

            # export yaml files
            utils.export_selected_rows_as_yaml(
                data, list_selected_rows, up_content, up_filename
            )

            # display alert if successful import
            # TODO: what is a better way to check if export was successful?
            # TODO: add timestamp? remove name of files in message?
            if not alert_state:
                alert_state = not alert_state
            list_files = [data[i]["File"] for i in list_selected_rows]
            alert_message = f"""Successfully exported
            {len(list_selected_rows)} yaml files: {list_files}"""

            # reset selected rows and nclicks
            list_selected_rows = []
            n_clicks_export = 0

        # If 'select/unselect all' button is clicked
        if (
            n_clicks_select_all % 2 != 0 and n_clicks_select_all > 0
        ):  # if odd number of clicks: select all
            list_selected_rows = list(range(len(data_page)))
        elif (
            n_clicks_select_all % 2 == 0 and n_clicks_select_all > 0
        ):  # if even number of clicks: unselect all
            list_selected_rows = []

        return (
            list_selected_rows,
            n_clicks_select_all,
            n_clicks_export,
            alert_state,
            alert_message,
        )