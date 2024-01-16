import argparse
import math
import operator as op
import os
import traceback
from functools import reduce
from pathlib import Path

import config_handler as cfg_hand
import numpy as np
import pandas as pd
from bokeh.models import HoverTool, Legend
from bokeh.models.sources import ColumnDataSource
from bokeh.palettes import viridis
from bokeh.plotting import figure, output_file, save
from bokeh.transform import factor_cmap
from config_handler import ConfigHandler
from perflog_handler import PerflogHandler
from titlecase import titlecase


class PostProcessing:

    def __init__(self, debug=False, verbose=False):
        # FIXME: add proper logging
        self.debug = debug
        self.verbose = verbose

    def run_post_processing(self, log_path, config_dict):
        """
            Return a dataframe containing the information passed to a plotting script
            and produce relevant graphs.

            Args:
                log_path: path, path to a log file or a directory containing log files.
                config_dict: dict, configuration information for plotting.
        """

        # find and read perflogs
        df = PerflogHandler(log_path, self.debug).read_all_perflogs()
        config = ConfigHandler(config_dict)

        invalid_columns = []
        # check for invalid columns
        for col in config.all_columns:
            if col not in df.columns:
                invalid_columns.append(col)
        if invalid_columns:
            raise KeyError("Could not find columns", invalid_columns)

        # apply column types
        self.apply_df_types(df, config.all_columns, config.column_types)
        # sort rows
        # NOTE: sorting here is necessary to ensure correct filtering + scaling alignment
        self.sort_df(df, config.x_axis, config.series_columns)
        # filter data
        mask = self.filter_df(df, config.and_filters, config.or_filters, config.series_filters)

        # get number of occurrences of each column
        series_col_count = {c: config.series_columns.count(c) for c in config.series_columns}
        # get number of column combinations
        series_combinations = reduce(op.mul, list(series_col_count.values()), 1)
        num_filtered_rows = len(df[mask])
        num_x_data_points = series_combinations * len(set(df[config.x_axis["value"]][mask]))
        # check expected number of rows
        if num_filtered_rows > num_x_data_points:
            raise RuntimeError("Unexpected number of rows ({0}) does not match \
                               number of unique x-axis values per series ({1})"
                               .format(num_filtered_rows, num_x_data_points), df[config.plot_columns][mask])

        # scale y-axis
        self.transform_df_data(df, config.x_axis, config.y_axis, config.series_filters, mask)

        print("Selected dataframe:")
        print(df[config.plot_columns][mask])

        # call a plotting script
        self.plot_generic(
            config.title, df[config.plot_columns][mask], config.x_axis, config.y_axis, config.series_filters)

        if self.debug & self.verbose:
            print("")
            print("Full dataframe:")
            print(df.to_json(orient="columns", indent=2))

        return df[config.plot_columns][mask]

    def apply_df_types(self, df: pd.DataFrame, all_columns, column_types):
        """
            Apply user-specified types to all relevant columns in the dataframe.

            Args:
                df: dataframe, benchmarking data.
                all_columns: list, names of important columns in the dataframe.
                column_types: dict, name-type pairs for important columns in the dataframe.
        """

        for col in all_columns:
            if column_types.get(col):

                # get user input type
                conversion_type = column_types[col]
                # allow user to specify "datetime" as a type (internally convert to "datetime64")
                conversion_type += "64" if conversion_type == "datetime" else ""

                # internal type conversion
                if pd.api.types.is_string_dtype(conversion_type):
                    # all strings treated as object (nullable)
                    conversion_type = "object"
                elif pd.api.types.is_float_dtype(conversion_type):
                    # all floats treated as float64 (nullable)
                    conversion_type = "float64"
                elif pd.api.types.is_integer_dtype(conversion_type):
                    # all integers treated as Int64 (nullable)
                    # NOTE: default pandas integer type is int64 (not nullable)
                    conversion_type = "Int64"
                elif pd.api.types.is_datetime64_any_dtype(conversion_type):
                    # all datetimes treated as datetime64[ns] (nullable)
                    conversion_type = "datetime64[ns]"
                else:
                    raise RuntimeError("Unsupported user-specified type '{0}' for column '{1}'."
                                       .format(conversion_type, col))

                # skip type conversion if column is already the desired type
                if conversion_type == df[col].dtype:
                    continue
                # otherwise apply type to column
                df[col] = df[col].astype(conversion_type)

            else:
                raise KeyError("Could not find user-specified type for column", col)

    def sort_df(self, df: pd.DataFrame, x_axis, series_columns):
        """
            Sort the given dataframe such that x-axis values and series are in ascending order.

            Args:
                df: dataframe, benchmarking data.
                x_axis: dict, x-axis column and units.
                series_columns: list, series column names.
        """

        sorting_columns = [x_axis["value"]]
        if series_columns:
            # NOTE: currently assuming there can only be one unique series column
            sorting_columns.append(series_columns[0])
        df.sort_values(sorting_columns, inplace=True, ignore_index=True)

    def filter_df(self, df: pd.DataFrame, and_filters, or_filters, series_filters):
        """
            Return a mask for the given dataframe based on user-specified filter conditions.

            Args:
                df: dataframe, benchmarking data.
                and_filters: list, filter conditions to be concatenated together with logical AND.
                or_filters: list, filter conditions to be concatenated together with logical OR.
                series_filters: list, like or_filters, but specifically for series.
        """

        mask = pd.Series(df.index.notnull())
        # filter rows
        if and_filters:
            mask = reduce(op.and_, (self.row_filter(f, df) for f in and_filters))
        if or_filters:
            mask &= reduce(op.or_, (self.row_filter(f, df) for f in or_filters))
        # apply series filters
        if series_filters:
            mask &= reduce(op.or_, (self.row_filter(f, df) for f in series_filters))
        # ensure not all rows are filtered away
        if df[mask].empty:
            raise pd.errors.EmptyDataError("Filtered dataframe is empty", df[mask].index)

        return mask

    def transform_df_data(self, df: pd.DataFrame, x_axis, y_axis, series_filters, mask):
        """
            Transform dataframe y-axis based on scaling settings.

            Args:
                df: dataframe, benchmarking data.
                x_axis: dict, x-axis column and units.
                y_axis: dict, y-axis column, units, and scaling information.
                series_filters: list, x-axis groups.
                mask: mask, dataframe filters.
        """

        # FIXME: overhaul this section
        scaling_column = None
        scaling_series_mask = None
        scaling_x_value_mask = None
        # extract scaling information
        if y_axis.get("scaling"):

            # check column information
            if y_axis["scaling"].get("column"):
                # copy scaling column (prevents issues when scaling by itself)
                scaling_column = df[y_axis["scaling"]["column"]["name"]].copy()
                # get mask of scaling series
                if y_axis["scaling"]["column"].get("series") is not None:
                    scaling_series_mask = self.row_filter(
                        series_filters[y_axis["scaling"]["column"]["series"]], df)
                # get mask of scaling x-value
                if y_axis["scaling"]["column"].get("x_value"):
                    scaling_x_value_mask = (
                        df[x_axis["value"]] == y_axis["scaling"]["column"]["x_value"])

            # check custom value is not zero
            elif not y_axis["scaling"].get("custom"):
                raise RuntimeError("Invalid custom scaling value (cannot divide by {0})."
                                   .format(y_axis["scaling"].get("custom")))

            # apply data transformation per series
            if series_filters:
                for f in series_filters:
                    m = self.row_filter(f, df)
                    df[mask & m] = self.transform_axis(
                        df[mask & m], mask & m, y_axis, scaling_column,
                        scaling_series_mask, scaling_x_value_mask)
            # apply data transformation to all data
            else:
                df[mask] = self.transform_axis(
                    df[mask], mask, y_axis, scaling_column,
                    scaling_series_mask, scaling_x_value_mask)

        # FIXME: add this as a config option at some point
        # if y_axis.get("drop_nan"):
        #    df.dropna(subset=[y_axis["value"]], inplace=True)
            # reset index
        #    df.index = range(len(df.index))

    def plot_generic(self, title, df: pd.DataFrame, x_axis, y_axis, series_filters):
        """
            Create a bar chart for the supplied data using bokeh.

            Args:
                title: str, plot title.
                df: dataframe, data to plot.
                x_axis: dict, x-axis column and units.
                y_axis: dict, y-axis column and units.
                series_filters: list, x-axis groups used to filter graph data.
        """

        # get column names and labels for axes
        x_column, x_label = get_axis_info(df, x_axis, series_filters)
        y_column, y_label = get_axis_info(df, y_axis, series_filters)

        # find x-axis groups (series columns)
        groups = [x_column]
        for f in series_filters:
            if f[0] not in groups:
                groups.append(f[0])
        # keep original x-axis dtype for sorting
        x_col_dtype = df[x_column].dtype
        last_group_dtype = df[groups[-1]].dtype
        # all x-axis data treated as categorical
        for g in groups:
            df[g] = df[g].astype(str)
        # combine group names for later plotting with groupby
        index_group_col = "_".join(groups)
        # group by group names (or just x-axis if no other groups are present)
        grouped_df = (df.groupby(x_column, sort=False) if len(groups) == 1
                      else df.groupby(groups, sort=False))

        if self.debug:
            print("")
            print("Plot x-axis groups:")
            for key, _ in grouped_df:
                print(grouped_df.get_group(key))

        # adjust y-axis range
        min_y = (0 if min(df[y_column]) >= 0
                 else math.floor(np.nanmin(df[y_column])*1.2))
        max_y = (0 if max(df[y_column]) <= 0
                 else math.ceil(np.nanmax(df[y_column])*1.2))

        # create html file to store plot in
        output_file(filename=os.path.join(
            Path(__file__).parent, "{0}.html".format(title.replace(" ", "_"))), title=title)

        # create plot
        plot = figure(x_range=grouped_df, y_range=(min_y, max_y), title=title,
                      width=800, toolbar_location="above")
        # configure tooltip
        plot.add_tools(HoverTool(tooltips=[
                                    (y_label, "@{0}_mean".format(y_column)
                                     + ("{%0.2f}" if pd.api.types.is_float_dtype(df[y_column].dtype)
                                        else ""))],
                                 formatters={"@{0}_mean".format(y_column): "printf"}))

        # sort x-axis values in descending order (otherwise default sort is ascending)
        reverse = False
        if x_axis.get("sort"):
            if x_axis["sort"] == "descending":
                reverse = True

        # sort x-axis groups by series first
        if len(groups) > 1:
            # get series values with their original dtype
            # NOTE: currently not accounting for more than one series column
            series_values = [pd.Series(x[-1], dtype=last_group_dtype).iloc[0]
                             for x in plot.x_range.factors]
            sorted_x_items = [x[1] for x in sorted(zip(series_values, plot.x_range.factors),
                                                   reverse=reverse, key=lambda x: x[0])]
            plot.x_range.factors = sorted_x_items

        # sort by x-axis values
        plot.x_range.factors = sorted(plot.x_range.factors, reverse=reverse,
                                      key=lambda x: pd.Series(x[0] if len(groups) > 1 else x,
                                                              dtype=x_col_dtype).iloc[0])

        # automatically base bar colouring on last group column
        colour_factors = [str(x) for x in sorted(pd.Series(df[groups[-1]].unique(),
                                                           dtype=last_group_dtype))]
        # divide and assign colours
        index_cmap = factor_cmap(index_group_col, palette=viridis(len(colour_factors)),
                                 factors=colour_factors, start=len(groups)-1, end=len(groups))
        # add legend labels to data source
        data_source = ColumnDataSource(grouped_df).data
        legend_labels = ["{0} = {1}".format(groups[-1].replace("_", " "),
                                            group[-1] if len(groups) > 1 else group)
                         for group in data_source[index_group_col]]
        data_source["legend_labels"] = legend_labels

        # create legend outside plot
        plot.add_layout(Legend(), "right")
        # add bars
        plot.vbar(x=index_group_col, top="{0}_mean".format(y_column), width=0.9, source=data_source,
                  line_color="white", fill_color=index_cmap, legend_group="legend_labels", hover_alpha=0.9)
        # add labels
        plot.xaxis.axis_label = x_label
        plot.yaxis.axis_label = y_label
        # remove x-axis group ticks
        plot.xaxis.major_tick_line_color = None
        plot.xaxis.major_label_text_font_size = "0pt"
        # FIXME: add this as a config option at some point
        # plot.xaxis.group_label_orientation = "vertical"
        # adjust font size
        plot.title.text_font_size = "15pt"

        # get label values with their original dtype
        label_values = [pd.Series(x.label.value.split("=")[1].strip(), dtype=last_group_dtype).iloc[0]
                        for x in plot.legend[0].items]
        # sort legend items (order determined by x-axis sort)
        sorted_legend_items = [x[1] for x in sorted(zip(label_values, plot.legend[0].items),
                                                    reverse=reverse, key=lambda x: x[0])]
        plot.legend[0].items = sorted_legend_items

        # save to file
        save(plot)

    # operator lookup dictionary
    op_lookup = {
        "==":   op.eq,
        "!=":   op.ne,
        "<":    op.lt,
        ">":    op.gt,
        "<=":   op.le,
        ">=":   op.ge
    }

    def row_filter(self, filter, df: pd.DataFrame):
        """
            Return a dataframe mask based on a filter condition. The filter is a list that
            contains a column name, an operator, and a value (e.g. ["flops_value", ">=", 1.0]).

            Args:
                filter: list, a condition based on which a dataframe is filtered.
                df: dataframe, used to create a mask by having the filter condition applied to it.
        """

        column, str_op, value = filter
        if self.debug:
            print("Applying row filter condition:", column, str_op, value)

        # check operator validity
        operator = self.op_lookup.get(str_op)
        if operator is None:
            raise KeyError("Unknown comparison operator", str_op)

        # evaluate expression and extract dataframe mask
        if value is None:
            mask = df[column].isnull() if operator == op.eq else df[column].notnull()
        else:
            try:
                # interpret comparison value as column dtype
                value = pd.Series(value, dtype=df[column].dtype).iloc[0]
                mask = operator(df[column], value)
            except TypeError or ValueError as e:
                e.args = (e.args[0] + " for column '{0}' and value '{1}'".format(column, value),)
                raise

        if self.debug & self.verbose:
            print(mask)
        if self.debug:
            print("")

        return mask

    def transform_axis(self, df: pd.DataFrame, df_mask, axis, scaling_column,
                       scaling_series_mask, scaling_x_value_mask):
        """
            Divide axis values by specified values and reflect this change in the dataframe.

            Args:
                df: dataframe, data to plot (pre-masked by series, if present).
                df_mask: bool list, the mask (pre-)applied to the df argument.
                axis: dict, axis column, units, and values to scale by.
                scaling_column: dataframe column, copy of column containing values to scale by.
                scaling_series_mask: bool list, a series mask to be applied to the scaling column.
                scaling_x_value_mask: bool list, an x-axis value mask to be applied to the scaling column.
        """

        # FIXME: try to make this an in-place process

        # scale by column
        if scaling_column is not None:

            # check types
            if (not pd.api.types.is_numeric_dtype(df[axis["value"]].dtype) or
                not pd.api.types.is_numeric_dtype(scaling_column.dtype)):
                # both columns must be numeric
                raise TypeError("Cannot scale column '{0}' of type {1} by column '{2}' of type {3}."
                                .format(axis["value"], df[axis["value"]].dtype,
                                        axis["scaling"]["column"]["name"], scaling_column.dtype))

            # get mask of scaling value(s)
            scaling_mask = df_mask.copy()
            if scaling_series_mask is not None:
                scaling_mask = scaling_series_mask
            if scaling_x_value_mask is not None:
                scaling_mask &= scaling_x_value_mask

            scaling_val = (scaling_column[scaling_mask].iloc[0] if len(scaling_column[scaling_mask]) == 1
                           else scaling_column[scaling_mask].values)

            # FIXME: add a check that the masked scaling column has the same number of values
            # as the masked df (unless there is only one scaling value)

            df[axis["value"]] = df[axis["value"]].values / scaling_val
            # FIXME: add this as a config option at some point in conjunction with dropping NaNs
            # df[axis["value"]].replace(to_replace=1, value=np.NaN, inplace=True)

        # scale by custom value
        elif axis["scaling"].get("custom"):
            scaling_value = axis["scaling"]["custom"]
            try:
                # interpret scaling value as column dtype
                scaling_value = pd.Series(scaling_value, dtype=df[axis["value"]].dtype).iloc[0]
            except ValueError as e:
                e.args = (e.args[0] + " as a scaling value for column '{0}'".format(axis["value"]),)
                raise
            df[axis["value"]] /= scaling_value

        return df


def read_args():
    """
        Return parsed command line arguments.
    """

    parser = argparse.ArgumentParser(
        description="Plot benchmark data. At least one perflog must be supplied.")

    # required positional arguments (log path, config path)
    parser.add_argument("log_path", type=Path,
                        help="path to a perflog file or a directory containing perflog files")
    parser.add_argument("config_path", type=Path,
                        help="path to a configuration file specifying what to plot")

    # optional argument (plot type)
    parser.add_argument("-p", "--plot_type", type=str, default="generic",
                        help="type of plot to be generated (default: 'generic')")

    # info dump flags
    parser.add_argument("-d", "--debug", action="store_true",
                        help="debug flag for printing additional information")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="verbose flag for printing more debug information \
                              (must be used in conjunction with the debug flag)")

    return parser.parse_args()


def get_axis_info(df: pd.DataFrame, axis, series_filters):
    """
        Return the column name and label for a given axis. If a column name is supplied as
        units information, the actual units will be extracted from a dataframe.

        Args:
            df: dataframe, data to plot.
            axis: dict, axis column, units, and values to scale by.
    """

    # get column name of axis
    col_name = axis.get("value")
    # get units
    units = axis.get("units").get("custom")
    if axis.get("units").get("column"):
        unit_set = set(df[axis["units"]["column"]].dropna())
        # check all rows have the same units
        if len(unit_set) != 1:
            raise RuntimeError("Unexpected number of axis unit entries {0}".format(unit_set))
        units = next(iter(unit_set))

    # get scaling information
    scaling = None
    if axis.get("scaling"):
        if axis["scaling"].get("column"):
            scaling_column = axis["scaling"]["column"]["name"]
            series_index = axis["scaling"]["column"].get("series")
            x_value = axis["scaling"]["column"].get("x_value")
            # FIXME: make scaling label more clear
            series_col = ("{0} in {1}".format(series_filters[series_index][2], scaling_column)
                          if series_index is not None else scaling_column)
            scaling = "{0} {1}".format(x_value, series_col) if x_value else series_col
        else:
            scaling = str(axis["scaling"].get("custom"))

    # determine axis label
    label = "{0}{1}{2}".format(titlecase(col_name.replace("_", " ")),
                               titlecase(" Scaled by {0}".format(scaling.replace("_", " ")))
                               if scaling else "",
                               " ({0})".format(units) if units else "")

    return col_name, label


def main():

    args = read_args()
    post = PostProcessing(args.debug, args.verbose)

    try:
        config = cfg_hand.open_config(args.config_path)
        cfg_hand.read_config(config)
        post.run_post_processing(args.log_path, config)

    except Exception as e:
        print(type(e).__name__ + ":", e)
        print("Post-processing stopped")
        if args.debug:
            print(traceback.format_exc())


if __name__ == "__main__":
    main()
