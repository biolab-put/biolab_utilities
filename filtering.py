#!/usr/bin/env python3

import time

import pandas as pd
import numpy as np

from scipy.optimize import minimize
from scipy.signal import butter, filtfilt

from . import putemg_utilities


__all__ = ["apply_filter"]


harmonic_x = lambda x, t: x[0] * np.sin(2 * np.pi * x[2] * t) + x[1] * (np.cos(2 * np.pi * x[2] * t))
harmonic_x_f = lambda x, t, f: x[0] * np.sin(2 * np.pi * f * t) + x[1] * (np.cos(2 * np.pi * f * t))
Q_x = lambda x, signal, t: np.sum([np.square(harmonic_x(x, t) - signal)]) / len(signal)
Q_x_f = lambda x, signal, t, f: np.sum([np.square(harmonic_x_f(x, t, f) - signal)]) / len(signal)


def Q_jacobian(x, signal, t):
    s = np.sin(2 * np.pi * x[2] * t)
    c = np.cos(2 * np.pi * x[2] * t)
    dx0 = 2 * np.sum([s * (x[0] * s + x[1] * c - signal)]) / len(signal)
    dx1 = 2 * np.sum([c * (x[0] * s + x[1] * c - signal)]) / len(signal)
    dx2 = 2 * np.sum([(2 * np.pi * t * x[0] * c + x[1] * (-2 * np.pi * t * s)) *
                      (x[0] * s + x[1] * c - signal)]) / len(signal)
    return np.array([dx0, dx1, dx2])


def Q_jacobian_f(x, signal, t, f):
    dx0 = 2 * np.sum([np.sin(2 * np.pi * f * t) * (
                x[0] * np.sin(2 * np.pi * f * t) + x[1] * (np.cos(2 * np.pi * f * t)) - signal)]) / len(signal)
    dx1 = 2 * np.sum([np.cos(2 * np.pi * f * t) * (
                x[0] * np.sin(2 * np.pi * f * t) + x[1] * (np.cos(2 * np.pi * f * t)) - signal)]) / len(signal)
    # dx2 = 2*np.sum([(2*np.pi*t*x[0]*np.cos(2*np.pi*x[2]*t)+x[1]*(-2*np.pi*t*np.sin(2*np.pi*x[2]*t)))*
    #                (x[0]*np.sin(2*np.pi*x[2]*t)+x[1]*(np.cos(2*np.pi*x[2]*t))-signal)])
    return np.array([dx0, dx1])


def multi_notch(series, window, notch_frequencies):
    windows_strided, indexes = putemg_utilities.moving_window_stride(series.values, np.int_(window), np.int_(window))
    indexes = np.append([0], indexes + 1)
    vec = np.zeros(np.shape(series))
    for freq in notch_frequencies:
        x_est = (0, 0, freq)
        i = 0
        for val in windows_strided:
            t0 = series.index[indexes[i]]
            t = np.arange(len(val)) / 5124.07211903 + t0
            bounds = ((None, None), (None, None), (freq - .01, freq + .01))
            res = minimize(Q_x, x_est, args=(val, t), method='L-BFGS-B', bounds=bounds, jac=Q_jacobian,
                           options={'gtol': 1e-6, 'disp': False})
            x_est = res.x
            vec[indexes[i]:indexes[i] + len(val)] += harmonic_x_f(x_est, t, x_est[2])
            x_est[2] = freq
            i = i + 1
    return vec


def butter_bandpass(low_cutoff, high_cutoff, fs, order=5):
    nyq = 0.5 * fs
    low = low_cutoff / nyq
    high = high_cutoff / nyq
    b, a = butter(order, [low, high], btype='band')
    return b, a


def butter_bandpass_filter(data, low_cutoff, high_cutoff, fs, order=5):
    b, a = butter_bandpass(low_cutoff, high_cutoff, fs, order=order)
    y = filtfilt(b, a, data)
    return y


def pre_process(signal, window_t=10, freq=5124.07211903, low_pass=20, high_pass=700):
    notch_frequencies = [30, 49.99, 90, 60, 150]
    val = multi_notch(signal, window_t * freq, notch_frequencies)
    signal = butter_bandpass_filter(signal - val, low_pass, high_pass, freq)

    return signal


def apply_filter(df: pd.DataFrame):
    start = time.time()
    columns = list(filter(lambda k: 'EMG' in k, df.columns))
    print('Processing channel: ', end='', flush=True)
    for channel_name in columns:
        print(' ' + channel_name, end='', flush=True)
        df[channel_name] = pre_process(df[channel_name])
    print('', flush=True)
    print("Elapsed time: {:.2f}s".format(time.time() - start))
