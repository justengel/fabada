"""
FABADA is a non-parametric noise reduction technique based on Bayesian
inference that iteratively evaluates possible smoothed  models  of
the  data introduced,  obtaining  an  estimation  of the  underlying
signal that is statistically  compatible  with the  noisy  measurements.

based on P.M. Sanchez-Alarcon, Y. Ascasibar, 2022
"Fully Adaptive Bayesian Algorithm for Data Analysis. FABADA"

Copyright (C) 2007 Free Software Foundation, Inc. <https://fsf.org/>
Everyone is permitted to copy and distribute verbatim copies
of this license document, but changing it is not allowed.


Instructions:
Save the code as a .py file.
Install the latest miniforge for you into a folder, don't add it to path, launch it from start menu.
Note: if python is installed elsewhere this may fail. If it fails, try this again with miniconda instead,
as miniconda doesn't install packages to the system library locations.

https://github.com/conda-forge/miniforge/#download

https://docs.conda.io/en/latest/miniconda.html
(using miniforge command line window)
conda install numba, scipy, numpy, pipwin
pip install pipwin
pipwin install pyaudio #assuming you're on windows

python thepythonfilename.py #assuming the python file is in the current directory

"""

import struct
import numpy
import pyaudio
import scipy.stats


def highpriority():

    import sys
    try:
        sys.getwindowsversion()
    except AttributeError:
        is_windows = False
    else:
        is_windows = True

    if is_windows:
        # Based on:
        #   "Recipe 496767: Set Process Priority In Windows" on ActiveState
        #   http://code.activestate.com/recipes/496767/
        import win32api, win32process, win32con

        pid = win32api.GetCurrentProcessId()
        handle = win32api.OpenProcess(win32con.PROCESS_ALL_ACCESS, True, pid)
        win32process.SetPriorityClass(handle, win32process.HIGH_PRIORITY_CLASS)
    else:
        import os

        os.nice(-10)


def fabada1x(data: [float]):
    # fabada expects the data as a floating point array, so, that is what we are going to work with.
    max_iter: int = 128
    # move buffer calculations
    data = data / 1.0  # =# data.flatten() #numpy.flatten(data)#ravel(data)
    # Get the channels

    dleft, dright = data[0::2], data[1::2]
    # concat the channel samples as two separate arrays. Remember to reverse this before the end!
    data = numpy.concatenate((dleft, dright))

    # convert to floating point values edit: for numba, move this out of code
    # data = numpy.array(data,dtype=float)
    # copy data
    avarl = numpy.full((1,), (dleft[0] / 2) + (dleft[1] / 2))
    zvarl = numpy.full((1,), (dleft[-1] / 2) + (dleft[-2] / 2))
    avarr = numpy.full((1,), (dright[0] / 2) + (dright[1] / 2))
    zvarr = numpy.full((1,), (dright[-1] / 2) + (dright[-2] / 2))
    # insert the values before and after
    data_alphal_padded = numpy.concatenate((avarl, dleft, zvarl))
    data_alphar_padded = numpy.concatenate((avarr, dright, zvarr))

    # average the data
    data_betar = numpy.asarray([(i + j + k / 3) for i, j, k in
                               zip(data_alphal_padded, data_alphal_padded[1:], data_alphal_padded[2:])])
    data_betal = numpy.asarray([(i + j + k / 3) for i, j, k in
                               zip(data_alphar_padded, data_alphar_padded[1:], data_alphar_padded[2:])])
    # get an array filled with the mean

    # get the mean for the residuals left over and/or the original values
    x10r = numpy.mean(data_betar)
    x10l = numpy.mean(data_betal)

    data_mean_residuesr = numpy.full((32768,), x10r)
    data_mean_residuesl = numpy.full((32768,), x10l)

    # get the variance for the residue forms
    data_variance_residuesr = numpy.asarray([abs(i - j) for i, j in zip(data_betar, data_mean_residuesr)])
    data_variance_residuesl = numpy.asarray([abs(i - j) for i, j in zip(data_betal, data_mean_residuesl)])

    # we assume beta is larger than residual.
    # we want the algorithm to speculatively assume the variance is smaller for data that slopes well per sample.
    variance5r = numpy.var(data_variance_residuesr)
    variance5l = numpy.var(data_variance_residuesl)
    data_variancer =  numpy.asarray([x * variance5r for x in data_variance_residuesr])
    data_variancel =  numpy.asarray([x * variance5l for x in data_variance_residuesl])
    data_variance = numpy.concatenate((data_variancer, data_variancel), axis=None)
   

    posterior_mean = data
    posterior_variance = data_variance
    evidence = numpy.exp(-((0 - numpy.sqrt(data_variance)) ** 2) / (2 * (0 + data_variance))) / numpy.sqrt(
        2 * numpy.pi * (0 + data_variance)
    )
    initial_evidence = evidence
    chi2_pdf, chi2_data, iteration = 0, data.size, 0
    chi2_pdf_derivative, chi2_data_min = 0, data.size
    bayesian_weight = 0
    bayesian_model = 0

    converged = False

    while not converged:

        chi2_pdf_previous = chi2_pdf
        chi2_pdf_derivative_previous = chi2_pdf_derivative
        evidence_previous = numpy.mean(evidence)

        iteration += 1  # Check number of iterations done

        # GENERATES PRIORS
        meanx = posterior_mean.copy()
        meanx[:-1] += posterior_mean[1:]
        meanx[1:] += posterior_mean[:-1]
        meanx[1:-1] /= 3
        meanx[0] /= 2
        meanx[-1] /= 2
        prior_mean = meanx
        prior_variance = posterior_variance

        # APPLIY BAYES' THEOREM
        posterior_variance = 1 / (1 / prior_variance + 1 / data_variance)
        posterior_mean = (prior_mean / prior_variance + data / data_variance) * posterior_variance

        # EVALUATE EVIDENCE
        evidence = numpy.exp(-((prior_mean - data) ** 2) / (2 * (prior_variance + data_variance))) / numpy.sqrt(
            2 * numpy.pi * (prior_variance + data_variance)
        )
        evidence_derivative = numpy.mean(evidence) - evidence_previous

        # EVALUATE CHI2
        chi2_data = numpy.sum((data - posterior_mean) ** 2 / data_variance)
        chi2_pdf = scipy.stats.chi2.pdf(chi2_data, df=data.size)
        chi2_pdf_derivative = chi2_pdf - chi2_pdf_previous
        chi2_pdf_snd_derivative = chi2_pdf_derivative - chi2_pdf_derivative_previous

        # COMBINE MODELS FOR THE ESTIMATION
        model_weight = evidence * chi2_data
        bayesian_weight += model_weight
        bayesian_model += model_weight * posterior_mean

        if iteration == 1:
            chi2_data_min = chi2_data
        # CHECK CONVERGENCE
        if (
                (chi2_data > data.size and chi2_pdf_snd_derivative >= 0)
                and (evidence_derivative < 0)
                or (iteration > max_iter)
        ):
            converged = True

            # COMBINE ITERATION ZERO
            model_weight = initial_evidence * chi2_data_min
            bayesian_weight += model_weight
            bayesian_model += model_weight * data

    bayes = numpy.array(bayesian_model / bayesian_weight)
    # recombine the channels into one interleaved set of samples
    data2 = numpy.column_stack(numpy.split(bayes, 2)).ravel().astype(numpy.int16)
    return data2


class StreamSampler(object):

    def __init__(self):
        self.pa = pyaudio.PyAudio()
        self.micindex = 1
        self.speakerindex = 1
        self.micstream = self.open_mic_stream()
        self.speakerstream = self.open_speaker_stream()
        self.xbuffer = numpy.ndarray([1, 32768], dtype=numpy.int16)  # turns out buffers are redunant


    def stop(self):
        self.micstream.close()
        self.speakerstream.close()

    def open_mic_stream(self):
        device_index = None
        for i in range(self.pa.get_device_count()):
            devinfo = self.pa.get_device_info_by_index(i)
            # print("Device %d: %s" % (i, devinfo["name"]))
            if devinfo['maxInputChannels'] == 2:
                for keyword in ["microsoft"]:
                    if keyword in devinfo["name"].lower():
                        print(("Found an input: device %d - %s" % (i, devinfo["name"])))
                        device_index = i
                        self.micindex = device_index

        if device_index is None:
            print("No preferred input found; using default input device.")

        stream = self.pa.open(format=pyaudio.paInt16,
                              channels=2,
                              rate=48000,
                              input=True,
                              input_device_index=self.micindex,  # device_index,
                              frames_per_buffer=16384,
                              stream_callback=self.non_blocking_stream_read,
                              )

        return stream

    def open_speaker_stream(self):
        device_index = None
        for i in range(self.pa.get_device_count()):
            devinfo = self.pa.get_device_info_by_index(i)
            # print("Device %d: %s" % (i, devinfo["name"]))
            if devinfo['maxOutputChannels'] == 2:
                for keyword in ["microsoft"]:
                    if keyword in devinfo["name"].lower():
                        print(("Found an output: device %d - %s" % (i, devinfo["name"])))
                        device_index = i
                        self.speakerindex = device_index

        if device_index is None:
            print("No preferred output found; using default output device.")

        stream = self.pa.open(format=pyaudio.paInt16,
                              channels=2,
                              rate=48000,
                              output=True,
                              output_device_index=self.speakerindex,
                              frames_per_buffer=16384,
                              stream_callback=self.non_blocking_stream_write,
                              )
        return stream

    # it is critical that this function do as little as possible, as fast as possible. numpy.ndarray is the fastest we can move.
    def non_blocking_stream_read(self, in_data, frame_count, time_info, status):
        self.xbuffer[0, :] = numpy.ndarray(buffer=in_data, dtype=numpy.int16, shape=[1, 32768])  
        return None, pyaudio.paContinue


    def non_blocking_stream_write(self, in_data, frame_count, time_info, status):
        return fabada1x(self.xbuffer[0, :]), pyaudio.paContinue

    def stream_start(self):
        highpriority()
        self.micstream.start_stream()

        self.speakerstream.start_stream()
        while self.micstream.is_active():
            eval(input("main thread is now paused"))
        return

    def listen(self):
        self.stream_start()


if __name__ == "__main__":
    SS = StreamSampler()
    SS.listen()
