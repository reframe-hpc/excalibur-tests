import argparse
import operator as op
import traceback
from functools import reduce
from pathlib import Path

import pandas as pd
from config_handler import ConfigHandler
from perflog_handler import PerflogHandler
from plot_handler import plot_generic


class PostProcessing:

    def __init__(self, log_path: Path, debug=False, verbose=False):
        # FIXME (issue #264): add proper logging
        self.debug = debug
        self.verbose = verbose
        # find and read perflogs
        self.original_df = PerflogHandler(log_path, self.debug).get_df()
        # copy original data for modification during post-processing
        self.df = self.original_df.copy()
        # dataframe filters
        self.mask = pd.Series(self.df.index.notnull())

    def run_post_processing(self, config: ConfigHandler):
        """
            Return a dataframe containing the information passed to a plotting script
            and produce relevant graphs.

            Args:
                config: ConfigHandler, class containing configuration information for plotting.
        """

        # FIXME (issue #265): consider hiding typing + sorting from user
        # because these steps must happen every time at the start

        # apply column types
        self.apply_df_types(config.all_columns, config.column_types)
        # sort rows
        # NOTE: sorting here is necessary to ensure correct filtering + scaling alignment
        self.sort_df(config.x_axis, config.series_columns)
        # get data filter mask
        self.mask = self.filter_df(*config.get_filters())
        self.check_filtered_row_count(
            config.x_axis["value"], [s[0] for s in config.series_filters], config.plot_columns)
        # scale y-axis
        self.transform_df_data(
            config.x_axis["value"], config.y_axis["value"], *config.get_y_scaling(), config.series_filters)

        # FIXME (#issue #255): have an option to put this into a file (-s / --save flag?)
        print("Selected dataframe:")
        print(self.df[self.mask][config.plot_columns])

        # call a plotting script
        self.plot = plot_generic(
            config.title, self.df[self.mask][config.plot_columns],
            config.x_axis, config.y_axis, config.series_filters, self.debug)

        # FIXME (#issue #255): maybe save this bit to a file as well for easier viewing
        if self.debug & self.verbose:
            print("")
            print("Full dataframe:")
            print(self.df.to_json(orient="columns", indent=2))

        return self.df[self.mask][config.plot_columns]

    def check_df_columns(self, all_columns):
        """
            Check that all columns listed in the config exist in the dataframe.

            Args:
                all_columns: list, names of all columns mentioned in the config.
        """

        invalid_columns = []
        # check for invalid columns
        for col in all_columns:
            if col not in self.df.columns:
                invalid_columns.append(col)
        if invalid_columns:
            raise KeyError("Could not find columns", invalid_columns)

    def apply_df_types(self, all_columns, column_types):
        """
            Apply user-specified types to all relevant columns in the dataframe.

            Args:
                all_columns: list, names of all columns mentioned in the config.
                column_types: dict, name-type pairs for all important columns.
        """

        # validate columns
        self.check_df_columns(all_columns)

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
                if conversion_type == self.df[col].dtype:
                    continue
                # otherwise apply type to column
                self.df[col] = self.df[col].astype(conversion_type)

            else:
                raise KeyError("Could not find user-specified type for column", col)

    def sort_df(self, x_axis, series_columns):
        """
            Sort the given dataframe such that x-axis values and series are in ascending order.

            Args:
                x_axis: dict, x-axis column and units.
                series_columns: list, names of series columns.
        """

        sorting_columns = [x_axis["value"]]
        if series_columns:
            # NOTE: currently assuming there can only be one unique series column
            sorting_columns.append(series_columns[0])
        self.df.sort_values(sorting_columns, inplace=True, ignore_index=True)

    def filter_df(self, and_filters, or_filters, series_filters):
        """
            Return a mask for the given dataframe based on user-specified filter conditions.

            Args:
                and_filters: list, filter conditions to be concatenated together with logical AND.
                or_filters: list, filter conditions to be concatenated together with logical OR.
                series_filters: list, function like or_filters but use series to select x-axis groups.
        """

        mask = pd.Series(self.df.index.notnull())
        # filter rows
        if and_filters:
            mask = reduce(op.and_, (self.row_filter(f, self.df) for f in and_filters))
        if or_filters:
            mask &= reduce(op.or_, (self.row_filter(f, self.df) for f in or_filters))
        # apply series filters
        if series_filters:
            mask &= reduce(op.or_, (self.row_filter(f, self.df) for f in series_filters))
        # ensure not all rows are filtered away
        if self.df[mask].empty:
            raise pd.errors.EmptyDataError("Filtered dataframe is empty", self.df[mask].index)

        return mask

    def check_filtered_row_count(self, x_column, series_columns, plot_columns):
        """
            Check that the filtered dataframe does not have an incompatible number of rows.
            Row number must match number of unique x-axis values per series.

            Args:
                x_column: str, name of x-axis column.
                series_columns: list, all names of series columns (including duplicates).
                plot_columns: list, names of all columns needed for plotting.
        """

        # get number of occurrences of each column
        series_col_count = {c: series_columns.count(c) for c in series_columns}
        # get number of column combinations
        series_combinations = reduce(op.mul, list(series_col_count.values()), 1)
        num_filtered_rows = len(self.df[self.mask])
        num_x_data_points = series_combinations * len(set(self.df[self.mask][x_column]))
        # check expected number of rows
        if num_filtered_rows > num_x_data_points:
            raise RuntimeError("Unexpected number of rows ({0}) does not match \
                               number of unique x-axis values per series ({1})"
                               .format(num_filtered_rows, num_x_data_points),
                               self.df[self.mask][plot_columns])

    def transform_df_data(self, x_column, y_column, scaling_column, scaling_custom, series_filters):
        """
            Transform dataframe y-axis based on scaling settings.

            Args:
                x_column: str, name of x-axis column.
                y_column: str, name of y-axis column.
                scaling_column: dict, name of scaling column, series index, and x-value information.
                scaling_custom: custom value to scale by.
                series_filters: list, x-axis group filters.
        """

        scaling_column_name = None
        scaling_value = None
        scaling_series_mask = None
        scaling_x_value_mask = None

        # scale by custom
        if scaling_custom:
            try:
                # interpret scaling value as column dtype
                scaling_value = pd.Series(scaling_custom, dtype=self.df[y_column].dtype)
            except ValueError as e:
                e.args = (e.args[0] + " as a scaling value for column '{0}'".format(y_column),)
                raise

        # scale by column
        elif scaling_column:
            # copy scaling column (prevents issues when scaling a column by itself)
            scaling_column_name = scaling_column.get("name")
            scaling_value = self.df[scaling_column_name].copy()
            # get mask of scaling series
            if scaling_column.get("series") is not None:
                scaling_series_mask = self.row_filter(series_filters[scaling_column.get("series")], self.df)
            # get mask of scaling x-value
            if scaling_column.get("x_value"):
                scaling_x_value_mask = (self.df[x_column] == scaling_column.get("x_value"))

        # apply scaling
        if scaling_value is not None:
            # apply data transformation per series
            if series_filters:
                for f in series_filters:
                    s = self.row_filter(f, self.df)
                    self.transform_axis(
                        self.mask & s, y_column, scaling_value, scaling_series_mask,
                        scaling_x_value_mask, scaling_column_name, scaling_custom)
            # apply data transformation to all data
            else:
                self.transform_axis(
                    self.mask, y_column, scaling_value, scaling_series_mask,
                    scaling_x_value_mask, scaling_column_name, scaling_custom)

        # FIXME (issue #253): add this as a config option at some point
        # if y_axis.get("drop_nan"):
        #    df.dropna(subset=[y_axis["value"]], inplace=True)
            # reset index
        #    df.index = range(len(df.index))

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

    def transform_axis(self, mask, axis_column, scaling_value, scaling_series_mask,
                       scaling_x_value_mask, scaling_column_name, scaling_custom):
        """
            Divide axis values by specified values and reflect this change in the dataframe.

            Args:
                mask: bool series, dataframe filters.
                axis_column: str, name of axis column to scale.
                scaling_value: dataframe column, copy of column containing values to scale by.
                scaling_series_mask: bool series, a series mask to be applied to the scaling column.
                scaling_x_value_mask: bool series, an x-axis value mask to be applied to the scaling column.
                scaling_column_name: str, name of scaling column.
                scaling_custom: custom value to scale by.
        """

        # prepare custom values
        if scaling_custom:
            scaling_value = scaling_value.iloc[0] if len(scaling_value) == 1 else scaling_value.values

        # prepare column values
        elif scaling_column_name:

            # check types
            if (not pd.api.types.is_float_dtype(self.df[mask][axis_column].dtype) or
                not pd.api.types.is_numeric_dtype(scaling_value.dtype)):
                # scaled column must be float to avoid casting issues and scaling column must be numeric
                raise TypeError("Cannot scale column '{0}' of type {1} by column '{2}' of type {3}. \
                                Scaled column must be float and scaling column must be numeric."
                                .format(axis_column, self.df[mask][axis_column].dtype,
                                        scaling_column_name, scaling_value.dtype))

            # get mask of scaling values
            scaling_mask = mask.copy()
            if scaling_series_mask is not None:
                scaling_mask = scaling_series_mask
            if scaling_x_value_mask is not None:
                scaling_mask &= scaling_x_value_mask

            scaling_value = (scaling_value[scaling_mask].iloc[0]
                             if len(scaling_value[scaling_mask]) == 1
                             else scaling_value[scaling_mask].values)

        # apply scaling
        self.df.loc[mask, axis_column] = self.df[mask][axis_column].values / scaling_value
        # FIXME (issue #253): add this as a config option at some point in conjunction with dropping NaNs
        # df[axis_column].replace(to_replace=1, value=np.NaN, inplace=True)


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


def main():

    args = read_args()

    try:
        post = PostProcessing(args.log_path, args.debug, args.verbose)
        config = ConfigHandler.from_path(args.config_path)
        post.run_post_processing(config)

    except Exception as e:
        print(type(e).__name__ + ":", e)
        print("Post-processing stopped")
        if args.debug:
            print(traceback.format_exc())


if __name__ == "__main__":
    main()
