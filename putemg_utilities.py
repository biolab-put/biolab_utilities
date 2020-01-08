import os
import re
import numpy as np
import pandas as pd
from typing import List, Dict, Sized
from scipy.special import comb
from scipy.ndimage.morphology import binary_dilation, binary_erosion
from scipy.signal import medfilt
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline


import warnings
import matplotlib.pyplot as plt
import ast
import math
from numpy.lib.stride_tricks import as_strided

import warnings
from sklearn.exceptions import DataConversionWarning

warnings.filterwarnings(action='ignore', category=DataConversionWarning)
warnings.filterwarnings(action='ignore', category=UserWarning, message='Variables are collinear')

__all__ = ["convert_types_in_dict", "moving_window_stride", "window_trapezoidal",
           "Record", "split", "record_filter", "filter_transitions", "filter_smart", "filter_recognition",
           "vgg_filter",
           "data_per_id", "data_per_id_and_date", "all_data_per_id", "prepare_data", "prepare_force_data",
           "normalized_confusion_matrix", "plot_confusion_matrix", "StandardScalerPerFeature",
           "prepare_pipeline", "normalise_force_data"]


def convert_types_in_dict(xml_dict):
    """
    Evaluates all dictionary entries into Python literal structure, as dictionary read from XML file is always string.
    If value can not be converted it passed as it is.
    :param xml_dict: Dict - Dictionary of XML entries
    :return: Dict - Dictionary with converted values
    """
    out = {}
    for el in xml_dict:
        try:
            out[el] = ast.literal_eval(xml_dict[el])
        except ValueError:
            out[el] = xml_dict[el]

    return out


def moving_window_stride(array, window, step):
    """
    Returns view of strided array for moving window calculation with given window size and step
    :param array: numpy.ndarray - input array
    :param window: int - window size
    :param step: int - step lenght
    :return: strided: numpy.ndarray - view of strided array, index: numpy.ndarray - array of indexes
    """
    stride = array.strides[0]
    win_count = math.floor((len(array) - window + step) / step)
    strided = as_strided(array, shape=(win_count, window), strides=(stride*step, stride))
    index = np.arange(window - 1, window + (win_count-1) * step, step)
    return strided, index


def window_trapezoidal(size, slope):
    """
    Return trapezoidal window of length size, with each slope occupying slope*100% of window
    :param size: int - window length
    :param slope: float - trapezoid parameter, each slope occupies slope*100% of window
    :return: numpy.ndarray - trapezoidal window
    """
    if slope > 0.5:
        slope = 0.5
    if slope == 0:
        return np.full(size, 1)
    else:
        return np.array([1 if ((slope * size <= i) & (i <= (1-slope) * size)) else (1/slope * i / size) if (i < slope * size) else (1/slope * (size - i) / size) for i in range(1, size + 1)])


class Record:
    def __init__(self, path: str = None):
        self.path: str = ""
        self.type: str = ""
        self.id: str = ""
        self.trajectory: str = ""
        self.date: str = ""
        self.time: str = ""
        if str:
            self.set_path(path)

    def set_path(self, path: str):
        experiment_name_regexp = r"^(?P<type>\w*)-(?P<id>\d{2})-(?P<trajectory>\w*)-" \
                                 r"(?P<date>\d{4}-\d{2}-\d{2})-(?P<time>\d{2}-\d{2}-\d{2}-\d{3})"

        basename = os.path.basename(path)

        tags = re.search(experiment_name_regexp, basename)
        if not tags:
            raise Warning("Wrong record", path)
        else:
            self.path = path
            self.type = tags.group('type')
            self.id = tags.group('id')
            self.trajectory = tags.group('trajectory')
            self.date = tags.group('date')
            self.time = tags.group('time')

    def print(self):
        for key in self.__dict__.keys():
            print(key, "=", self.__dict__[key])

    def __repr__(self):
        return "-".join([self.type, self.id, self.trajectory, self.date, self.time])

    def __str__(self):
        return "-".join([self.type, self.id, self.trajectory, self.date, self.time])

    def __hash__(self):
        return hash(self.__repr__())

    def __eq__(self, other):
        return isinstance(self, type(other)) and self.__repr__() == other.__repr__()


def split(items: Sized, n_splits=None, test_size=0.1, train_size=None, random_state=None):
    rng1 = np.random.RandomState(random_state)

    if test_size is None and train_size is None:
        raise ValueError("Missing test size or train size")

    data_count = len(items)

    items = set(range(data_count))

    if isinstance(train_size, float):
        train_size = np.rint(train_size * data_count)
    if isinstance(test_size, float):
        test_size = np.rint(test_size * data_count)
    if train_size is None:
        train_size = data_count - test_size
    if test_size is None:
        test_size = data_count - train_size

    train_size = int(train_size)
    test_size = int(test_size)

    if train_size < 1 or train_size > (data_count - 1):
        raise ValueError("Wrong train size: train_size={:d},test_size={:d} out of {:d}".
                         format(train_size, test_size, data_count))
    if test_size < 1 or test_size > (data_count - 1):
        raise ValueError("Wrong test size: train_size={:d},test_size={:d} out of {:d}".
                         format(train_size, test_size, data_count))

    n_comb = int(comb(data_count, train_size) * comb(data_count - train_size, test_size))

    if n_splits is None:
        n_splits = n_comb
    if n_splits > n_comb:
        warnings.warn("n_splits larger than available ({:d}/{:d})".format(n_splits, n_comb))
        n_splits = n_comb

    splits = []
    while len(splits) < n_splits:
        items_train = rng1.choice(list(items), size=train_size, replace=False)
        items_left = items.copy()
        for it in items_train:
            items_left.remove(it)
        items_test = rng1.choice(list(items_left), size=test_size, replace=False)
        split_candidate = (set(items_train), set(items_test))
        if split_candidate not in splits:
            splits.append(split_candidate)

    return splits


def record_filter(records: List[Record], whitelists: Dict[str, List] = None, blacklists: Dict[str, List] = None):
    filtered_records: List[Record] = []
    if whitelists is None:
        whitelists = {}
    if blacklists is None:
        blacklists = {}
    for r in records:
        keep: bool = True
        for w_key, w_values in whitelists.items():
            if getattr(r, w_key) not in w_values:
                keep = False
                break
        if keep:
            for b_key, b_values in blacklists.items():
                if getattr(r, b_key) in b_values:
                    keep = False
                    break
        if keep:
            filtered_records.append(r)
    return filtered_records


def filter_transitions(trajectory: np.ndarray,
                       start_before: int = 0, start_after: int = 0,
                       end_before: int = 0, end_after: int = 0,
                       pause_before: int = 0, pause_after: int = 0):
    trajectory_nan = trajectory.astype('float')
    np.putmask(trajectory_nan, trajectory_nan < 0, np.nan)

    diffs = np.concatenate(([0], np.diff(trajectory_nan)))
    np.putmask(diffs, np.isnan(diffs), 0)

    filtered = trajectory.copy()

    mask = np.full(trajectory.shape, False)
    if start_before > 0:
        start_before_mask = np.logical_and(diffs != 0, trajectory > 0)
        if start_before > 1:
            start_before_mask = binary_dilation(start_before_mask, structure=np.array([1, 1, 0]),
                                                iterations=start_before-1)
        mask = np.logical_or(mask, start_before_mask)

    if start_after > 0:
        start_after_mask = np.logical_and(diffs != 0, trajectory > 0)
        start_after_mask = binary_dilation(start_after_mask, structure=np.array([1, 0, 0]))  # shift left
        if start_after > 1:
            start_after_mask = binary_dilation(start_after_mask, structure=np.array([0, 1, 1]),
                                               iterations=start_after-1)
        mask = np.logical_or(mask, start_after_mask)

    if end_before > 0:
        end_before_mask = np.logical_and(diffs != 0, trajectory == 0)
        if end_before > 1:
            end_before_mask = binary_dilation(end_before_mask, structure=np.array([1, 1, 0]),
                                              iterations=end_before-1)
        mask = np.logical_or(mask, end_before_mask)

    if end_after > 0:
        end_after_mask = np.logical_and(diffs != 0, trajectory == 0)
        end_after_mask = binary_dilation(end_after_mask, structure=np.array([1, 0, 0]))  # shift left
        if end_after > 1:
            end_after_mask = binary_dilation(end_after_mask, structure=np.array([0, 1, 1]),
                                             iterations=end_after-1)
        mask = np.logical_or(mask, end_after_mask)

    filtered[mask] = -5

    pause_mask = trajectory == -1

    if pause_before > 0:
        pause_mask = binary_dilation(pause_mask, structure=np.array([1, 1, 0]), iterations=pause_before)
    if pause_after > 0:
        pause_mask = binary_dilation(pause_mask, structure=np.array([0, 1, 1]), iterations=pause_after)

    filtered[pause_mask] = -6

    return filtered


def filter_smart(recognized: np.ndarray, trajectory: np.ndarray,
                 recognition_median_filter: int = 5,
                 recognition_tolerance_backward: int = 8,
                 recognition_tolerance_forward: int = 1,
                 min_idle_period: int = 7):

    trajectory_length = len(recognized)

    recognized_median = medfilt(recognized, recognition_median_filter)

    idle_mask = binary_erosion(recognized_median <= 0, iterations=int(min_idle_period/2))
    idle_mask = binary_dilation(idle_mask, iterations=int(min_idle_period/2))

    transitions = np.concatenate(([0], np.diff(idle_mask) != 0))

    starts_mask = np.logical_and(transitions, recognized_median != 0)
    starts = np.flatnonzero(starts_mask)

    ends_mask = np.logical_and(transitions, recognized_median == 0)
    ends = np.flatnonzero(ends_mask)

    output = np.full(recognized.shape, -4)
    np.putmask(output, idle_mask, 0)
    np.putmask(output, recognized < 0, recognized.astype('int32'))

    for i, s in enumerate(starts.tolist()):
        t_idx = np.searchsorted(ends, s+1)
        if t_idx < len(ends):
            t = ends[t_idx]
        else:
            t = trajectory_length-1

        trajectory_s = max(0, s-recognition_tolerance_backward)
        trajectory_t = min(t+recognition_tolerance_forward, trajectory_length-1)

        gesture = np.median(recognized[s:t])
        if gesture in trajectory[trajectory_s:trajectory_t]:
            output[s:t] = gesture

    return output


def vgg_filter(recognized: np.ndarray, trajectory: np.ndarray,
               recognition_median_filter: int = 7,
               recognition_tolerance_early: int = 1,
               recognition_tolerance_late: int = 8):
    recognized_filtered = medfilt(recognized, recognition_median_filter)
    gestures = np.unique(trajectory)
    for g in gestures:  # reject mistakes outside of tolerance range -> -1
        if g != 0:
            g_mask = trajectory == g
            if recognition_tolerance_early > 0:
                g_mask = binary_dilation(g_mask, structure=np.array([1, 1, 0]), iterations=recognition_tolerance_early)
            if recognition_tolerance_late > 0:
                g_mask = binary_dilation(g_mask, structure=np.array([0, 1, 1]), iterations=recognition_tolerance_late)
            np.putmask(recognized_filtered, np.logical_and(recognized_filtered == g, np.logical_not(g_mask)), -1)

    return recognized_filtered


def filter_recognition(recognized: np.ndarray, trajectory: np.ndarray, gestures, margin_l: int = 1, margin_r: int = 8):
    recognized_filtered = recognized.copy()
    for g in gestures:
        trajectory_mask = trajectory == g

        if margin_l > 0:
            trajectory_mask = binary_dilation(trajectory_mask, structure=np.array([1, 1, 0]), iterations=margin_l)
        if margin_r > 0:
            trajectory_mask = binary_dilation(trajectory_mask, structure=np.array([0, 1, 1]), iterations=margin_r)

        recognized_filtered[np.logical_and(recognized == g, ~trajectory_mask)] = -2

    return recognized_filtered


def data_per_id(records: List[Record], n_splits: int = None) -> Dict[str, List[Dict[str, List[Record]]]]:
    ids = {r.id for r in records}

    sets = {}

    for i in sorted(ids):
        print("id={:}".format(i))
        rec_i = record_filter(records, whitelists={"id": [i]})
        available_dates = sorted(list({r.date for r in rec_i}))
        print("", rec_i)

        splits = split(available_dates, n_splits=n_splits, test_size=0.4, random_state=0)

        record_splits = []
        for train_index, test_index in splits:
            train_dates = [available_dates[idx] for idx in train_index]
            train_records = record_filter(rec_i, whitelists={"date": train_dates})

            test_dates = [available_dates[idx] for idx in test_index]
            test_records = record_filter(rec_i, whitelists={"date": test_dates})
            record_splits.append({"train": train_records, "test": test_records})

            print("train:", train_dates, "test:", test_dates)
        sets["{:}".format(i)] = record_splits
    return sets


def data_per_id_and_date(records: List[Record], n_splits: int = None):
    ids = {r.id for r in records}

    sets = {}

    for i in sorted(ids):
        rec_i = record_filter(records, whitelists={"id": [i]})
        available_dates = sorted(list({r.date for r in rec_i}))
        for d in available_dates:
            s = "{:}/{:}".format(i, d)

            rec_i_d = record_filter(rec_i, whitelists={"date": [d]})

            splits = split(rec_i_d, n_splits=n_splits, test_size=0.4, random_state=0)

            record_splits = []

            for train_index, test_index in splits:
                train_records = [rec_i_d[i2] for i2 in train_index]
                test_records = [rec_i_d[i2] for i2 in test_index]
                record_splits.append({"train": train_records, "test": test_records})

            sets[s] = record_splits
    return sets


def all_data_per_id(records: List[Record]):
    ids = {r.id for r in records}

    sets = {}

    for i in sorted(ids):
        rec_i = record_filter(records, whitelists={"id": [i]})
        s = "{:}".format(i)
        sets[s] = [{"all": rec_i}]
    return sets


def prepare_data(dfs: Dict[Record, pd.DataFrame], s: Dict[str, List[Record]], features: List[str], gestures: List[int]):
    metadata = ['TRAJ_1', 'type', 'subject', 'trajectory', 'date_time', 'TRAJ_GT', 'VIDEO_STAMP']

    dfs_output: Dict[str, pd.DataFrame] = dict()
    column_regex = re.compile("^((" + ")|(".join(features) + "))_[0-9]+")

    for k, v in s.items():
        df_temp = pd.DataFrame()
        columns_input = []
        for r in v:
            columns_input = list(filter(column_regex.match, list(dfs[r])))
            df_temp = df_temp.append(dfs[r][columns_input + metadata])

        df_temp["original_time"] = df_temp.index

        # label filtering deprecated as labeling vgg labels are already filtered
        # df_temp["output_0"] = filter_smart(df_temp["TRAJ_GT"].values, df_temp["TRAJ_1"].values)
        # df_temp["output_0"] = vgg_filter(df_temp["TRAJ_GT"].values, df_temp["TRAJ_1"].values)

        df_temp["output_0"] = filter_transitions(df_temp["TRAJ_GT"].values,
                                                 start_before=2, start_after=1,
                                                 end_before=0, end_after=0,
                                                 pause_before=0, pause_after=4)

        df_temp.rename({c: "input_{:d}_{:s}".format(i, c) for i, c in enumerate(columns_input)},
                       axis="columns", inplace=True)

        dfs_output[k] = df_temp.loc[df_temp["output_0"] >= 0]
        dfs_output[k].index = np.arange(0, len(dfs_output[k].index))
    return dfs_output


def prepare_force_data(dfs: Dict[Record, pd.DataFrame], s: Dict[str, List[Record]],
                       features: List[str], force_feature: str, trajectory: List[int]):
    dfs_output: Dict[str, Dict[str, pd.DataFrame]] = dict()

    emg_feature_column_regex = re.compile("^((" + ")|(".join(features) + "))_[0-9]+")
    force_feature_column_regex = re.compile("^FORCE_" + force_feature +
                                            "_((" + ")|(".join(list(map(str, trajectory))) + "))")

    for data_type, files in s.items():
        dfs_output[data_type]: Dict[str, pd.DataFrame] = dict()
        dfs_output[data_type]["input"] = pd.DataFrame()
        dfs_output[data_type]["output"] = pd.DataFrame()

        for record in files:
            emg_features_columns_input = list(filter(emg_feature_column_regex.match, list(dfs[record])))
            dfs_output[data_type]["input"] = dfs_output[data_type]["input"].append(
                dfs[record][emg_features_columns_input])

            force_feature_columns_output = list(filter(force_feature_column_regex.match, list(dfs[record])))
            dfs_output[data_type]["output"] = dfs_output[data_type]["output"].append(
                dfs[record][force_feature_columns_output])

        dfs_output[data_type]["input"].index = np.arange(0, len(dfs_output[data_type]["input"].index))
        dfs_output[data_type]["output"].index = np.arange(0, len(dfs_output[data_type]["output"].index))

    return dfs_output


def normalized_confusion_matrix(cm):
    return cm.astype('float') / cm.sum(axis=1)[:, np.newaxis]


def plot_confusion_matrix(cm, classes,
                          normalize=False,
                          title=None,
                          cmap=plt.cm.Blues, ax=None):
    """
    This function prints and plots the confusion matrix.
    Normalization can be applied by setting `normalize=True`.
    """
    if not title:
        if normalize:
            title = 'Normalized confusion matrix'
        else:
            title = 'Confusion matrix, without normalization'

    # Compute confusion matrix
    # cm = confusion_matrix(y_true, y_pred)
    # Only use the labels that appear in the data
    # classes = classes[unique_labels(y_true, y_pred)]
    if normalize:
        cm = normalized_confusion_matrix(cm)
        print("Normalized confusion matrix")
    else:
        print('Confusion matrix, without normalization')

    print(cm)

    if ax is None:
        fig, ax = plt.subplots()
    im = ax.imshow(cm, interpolation='nearest', cmap=cmap)
    ax.figure.colorbar(im, ax=ax)
    # We want to show all ticks...
    ax.set(xticks=np.arange(cm.shape[1]),
           yticks=np.arange(cm.shape[0]),
           # ... and label them with the respective list entries
           xticklabels=classes, yticklabels=classes,
           title=title,
           ylabel='True label',
           xlabel='Predicted label')

    # Rotate the tick labels and set their alignment.
    plt.setp(ax.get_xticklabels(), rotation=45, ha="right",
             rotation_mode="anchor")

    # Loop over data dimensions and create text annotations.
    fmt = '.2f' if normalize else 'd'
    thresh = cm.max() / 2.
    for i in range(cm.shape[0]):
        for j in range(cm.shape[1]):
            ax.text(j, i, format(cm[i, j], fmt),
                    ha="center", va="center",
                    color="white" if cm[i, j] > thresh else "black")
    # fig.tight_layout()
    return ax


class StandardScalerPerFeature(StandardScaler):

    def fit(self, X: pd.DataFrame, y=None):
        features = [re.match(r"input_[0-9]+_([A-Z]+)_[0-9]+", l).group(1) for l in list(X)]
        unique_features = list(set(features))

        fit_data = pd.DataFrame(columns=features)

        for uf in unique_features:
            uf_data = X.filter(regex="input_[0-9]+_" + uf + "_[0-9]+").values.reshape(-1, 1).astype(float)
            fit_data[uf] = uf_data[:, 0]

        return super().fit(fit_data, y)


def prepare_pipeline(train_in: pd.DataFrame, train_out: pd.DataFrame,
                     predictor: str, norm_per_feature: bool = False,
                     **predictor_args):

    if norm_per_feature:
        scaler = StandardScalerPerFeature()
    else:
        scaler = StandardScaler()

    if predictor == "LDA":
        from sklearn.discriminant_analysis import LinearDiscriminantAnalysis
        predictor_instance = LinearDiscriminantAnalysis(**predictor_args)
    elif predictor == "QDA":
        from sklearn.discriminant_analysis import QuadraticDiscriminantAnalysis
        predictor_instance = QuadraticDiscriminantAnalysis(**predictor_args)
    elif predictor == "kNN":
        from sklearn.neighbors import KNeighborsClassifier
        predictor_instance = KNeighborsClassifier(**predictor_args)
    elif predictor == "SVM":
        from sklearn.svm import SVC
        predictor_instance = SVC(**predictor_args)
    elif predictor == "LR":
        from sklearn.linear_model import LinearRegression
        predictor_instance = LinearRegression(**predictor_args)
    elif predictor == "SVR":
        from sklearn.svm import SVR
        predictor_instance = SVR(**predictor_args)
    elif predictor == "MLPR":
        from sklearn.neural_network import MLPRegressor
        predictor_instance = MLPRegressor(**predictor_args)
    else:
        raise ValueError(predictor + ' is not a valid predictor')

    pipe = Pipeline([('scaler', scaler), ('predictor', predictor_instance)])

    pipe.fit(train_in, train_out)

    return pipe


def normalise_force_data(data: pd.DataFrame, mvc: pd.DataFrame):
    emg_mvc_columns = list(filter(lambda k: 'EMG' in k, mvc.columns))

    # extract only MVC active part
    emg_mvc_data = mvc[emg_mvc_columns][binary_erosion(mvc['TRAJ_1'] > 0, iterations=2000)].values

    # calculate scaler as mean value of 5 highest RMS
    emg_mvc_rms = np.sqrt(np.mean(np.square(emg_mvc_data), axis=0))
    emg_mvc_scaler = np.mean(emg_mvc_rms[emg_mvc_rms.argsort()[-5:]])

    # read scaler for force from file
    force_mvc_scaler = mvc['FORCE_MVC'].values[0]

    # new DataFrame for normalised data
    scaled_frame = pd.DataFrame()

    # scale EMG write to new DF
    emg_columns = list(filter(lambda k: 'EMG' in k, data.columns))
    scaled_frame[emg_columns] = data[emg_columns] / emg_mvc_scaler

    # scale FORCE and TRAJ
    force_traj_columns = list(filter(lambda k: ('FORCE' in k) or ('TRAJ' in k), data.columns))
    force_scaled = data[force_traj_columns] / force_mvc_scaler

    force_groups = {
        '1': ['FORCE_1', 'FORCE_2'],
        '2': ['FORCE_3', 'FORCE_4'],
        '3': ['FORCE_5', 'FORCE_6'],
        '4': ['FORCE_7', 'FORCE_8', 'FORCE_9', 'FORCE_10']
    }

    # mean the values of force to correspond with TRAJ
    for g_name, g_list in force_groups.items():
        scaled_frame['FORCE_' + g_name] = np.mean(force_scaled[g_list], axis=1)
        scaled_frame['TRAJ_' + g_name] = force_scaled['TRAJ_' + g_name]

    # add remaining columns
    other_columns = list(filter(lambda k: not (('FORCE' in k) or ('EMG' in k) or ('TRAJ' in k)), data.columns))
    scaled_frame[other_columns] = data[other_columns]

    return scaled_frame