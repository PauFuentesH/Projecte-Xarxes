import numpy as np
import pandas as pd
import os.path
import torch
from pathlib import Path,PureWindowsPath,PurePosixPath
import matplotlib.pyplot as plt
import librosa
from torch.utils.data.dataloader import DataLoader, Dataset
import tqdm
from sklearn.model_selection import train_test_split
from sklearn.metrics import confusion_matrix
import seaborn as sns
import ast
import random

# Number of samples per 30s audio clip.
SAMPLING_RATE = 44100


    
def GetGenres(path,dict_genre,tracks):  #Returns two arrays, one with ID's the other with their genres
    """
    Finds the genre of each audio file through the id and the tracks dataset, returns the sorted list of ids and genres of each sample.
    Also encodes the genres.

    Parameters:
    - path: Path where the audio files are located.
    - dict_genre: Dictionary used to encode the genres from strings to ints.
    - tracks: Tracks Dataset.

    Return:
    - id_list: Array containing the id of each song.
    - genre_list: Array containing the genre of each song.
    """

    id_list = []       
    genre_list = []                                
    for direc in list(path.iterdir()):
        if direc.is_file():
            id_track = str(direc)[-10:-4]
            id_list.append(id_track)
            genre_list.append(dict_genre[tracks.loc[tracks.track_id == int(id_track),'genre_top'].values[0]]) #Gets only the top genre
    return np.asarray(id_list),np.asarray(genre_list)



def CreateSpectrograms(load_path,save_path): 
    """
    Loads each song and creates its Mel Spectrogram using librosa, with Fast Fourier Transform window of 2048 and a 
    hop length of 512. It also saves the spectrogram on the save defined path with the id as the name and it reduces the channel 
    of the audio to one (mono and not stereo) if it has 2 channels.

    Parameters:
    - load_path: Path where the audios to load are found.
    - save_path: Path where we the spectrograms are saved.
    """

    for file in list(load_path.iterdir()):
        id_track = str(file)[-10:-4]
        try:
            waveform, sample_rate = librosa.load(file)
            spec = librosa.feature.melspectrogram(y=waveform, sr=sample_rate, n_fft = 2048,hop_length=512 )
            if waveform.shape[0] > 1:
                    waveform = (waveform[0] + waveform[1])/2
            torch.save(spec, str(save_path)+"/"+id_track+".pt")
            
        except:
            pass

def ChargeDataset(path,id_list,genre_list):
    """
    Loads the spectrograms and also the genres of each spectrogram created.

    Parameters:
    - path: Path where the spectrogram are found.
    - id_list: List with the id of each track.
    - genre_list: List with the genre of each track.

    Return:
    - images: List containing the spectrograms of each track.
    - labels: List containing the genres of each track.
    """
    
    images = []
    labels = []
    for i,spec in enumerate(list(path.iterdir())):
        id_track = str(spec)[18:-3]
        labels.append(genre_list[np.argwhere(id_list == id_track)][0][0]) #Finds the index of the id to get the genre
        
        spec = torch.load(spec)
        spec = np.asarray(librosa.power_to_db(spec))
        images.append(spec)
        
    return images,labels


def plot_spectrogram(spec, title=None, ylabel="freq_bin", xmax=None):
    """
    Allows to plot the spectrogram.

    Parameters:
    - spec: Spectrogram to plot.
    - title: Title of the plot. None as default.
    - ylabel: Label og the y axis. "freq_bin" as default.
    - xmax: Max value of the x axis. None as default.
    """

    fig, axs = plt.subplots(1, 1)
    axs.set_title(title or "Spectrogram (db)")
    axs.set_ylabel(ylabel)
    axs.set_xlabel("frame")
    im = axs.imshow(spec, origin="lower", aspect="auto")
    if xmax:
        axs.set_xlim((0, xmax))
    fig.colorbar(im, ax=axs)
    plt.show(block=False)

class CustomSpectrogramDataset(Dataset):
    """
    Class used to create the dataset of the Spectrograms for the PyTorch models.
    """

    def __init__(self, spectrogram,genre, transform=None):
        self.x = spectrogram
        self.target = genre
        self.transform = transform

    def __len__(self):
        return len(self.target)

    def __getitem__(self, idx):
        image = self.x[idx]
        label = self.target[idx]
        if (self.transform!=None):
            image = self.transform(image)
        return image, label


def FixSizeSpectrogram(spectrograms,genres,shapes):
    """
    Fixes the size of all spectrograms, making them all of the same size so convolutions can be done.

    Parameters:
    - spectrograms: List containing all the spectrograms.
    - genres: List containing all the genres associated to the spectrograms.
    - shapes: Array with all the shapes found. First value corresponds to the height (frequency), which is equal for all 
              spectrograms, and second corresponds to the smallest value of the width (time), which will be the new value for all of them.

    Returns: 
    - spectrograms_list: List containing the spectrograms of each track.
    - genres_list: List containing the genres of each track.
    """

    spectrograms_list = []
    genres_list = []

    for i,spec in enumerate(spectrograms):
        if spec.shape != (shapes[0],shapes[1]):
            spectrograms_list.append(spec[0:shapes[0],0:shapes[1]])
            genres_list.append(genres[i])
            
        else:
            spectrograms_list.append(spec)
            genres_list.append(genres[i])

    return spectrograms_list, genres_list

def LoadFixCSV():
    """
    Read data from csv files and prepare it adequately.

    Returns:
    - tracks: Dataframe containing information of each track.
    - genres: Dataframe containing information of each genre.
    """
    tracks = pd.read_csv("./data/tracks.csv", low_memory=False)
    genres = pd.read_csv("./data/genres.csv")
    tracks.columns=tracks.iloc[0] 
    tracks.columns.values[0] = "track_id"
    tracks.drop([0,1],inplace=True)
    tracks.track_id = tracks.track_id.astype(int)

    return tracks,genres

def CreateTrainTestLoaders(spectrograms_list, genres_list, train_size, train_kwargs, test_kwargs,dataaugment=False):
    """
    Splits data into train/test sets, implements data augmentation (if desired) and creates both dataloaders.

    Parameters:
    - spectrograms_list: List containing the spectrograms of each track.
    - genres_list: List containing the genres of each track.
    - train_size: Percentage of the data that is dedicated to train.
    - train_kwargs: Batch size of training set.
    - test_kwargs: Batch size of test set.
    - dataaugment: Decides if data augmentation is used or not, by default it is False.

    Returns:
    - train_dataloader: Dataloader of training set.
    - test_dataloader: Dataloader of test set.
    - y_val: List with the genres used for the test set.
    """
    train_mean = np.mean(spectrograms_list)/255. #Mean of all images
    train_std = np.std(spectrograms_list)/255. 

    X_train, X_val, y_train, y_val = train_test_split(spectrograms_list, genres_list, train_size=train_size, stratify=genres_list)
    
    if dataaugment:
        DataSpecAugmentation(X_train, y_train)

    train_ds = CustomSpectrogramDataset(X_train, y_train)
    test_ds = CustomSpectrogramDataset(X_val, y_val)

    train_dataloader = torch.utils.data.DataLoader(train_ds, **train_kwargs)
    test_dataloader = torch.utils.data.DataLoader(test_ds, **test_kwargs)


    return train_dataloader, test_dataloader, y_val


def LoadDataPipeline():
    """
    Function used to Load the data and prepare it to create the dataloaders

    Returns:
    - spectrograms_list: List containing the spectrograms of each track.
    - genres_list: List containing the genres of each track.
    """
    tracks, genres = LoadFixCSV()
    print("Tracks and Genres loaded")
    genre_dict = {'Electronic':0,'Experimental':1,'Folk':2,'Hip-Hop':3,
             'Instrumental':4, 'International':5, 'Pop':6, 'Rock':7}

    path = Path("./data/audio")
    id_list, genre_list = GetGenres(path,genre_dict,tracks)
    save_path = Path("./data/Spectrograms")
    if len(list(save_path.iterdir())) != 7994:
        CreateSpectrograms(path,save_path)
    print("Spectrograms created")
    spectrograms, genres = ChargeDataset(save_path,id_list,genre_list)
    print("Spectrograms loaded")

    shape = []
    for i in spectrograms:
        shape.append(i.shape)
    shapes = np.unique(shape)


    spectrograms_list, genres_list = FixSizeSpectrogram(spectrograms,genres,shapes)
    print("Size fixed for Spectrograms")


    return spectrograms_list, genres_list


def DataSpecAugmentation(spec_list, genres_list):
    """
    Implement data augmentation to try to increase the performance of the model. 
    """
    new_spec = []
    genre_augment = []

    for i,spec in enumerate(spec_list):
        spec = spec_augment(spec)
        new_spec.append(spec)
        genre_augment.append(genres_list[i])

    spec_list.extend(new_spec)
    genres_list.extend(genre_augment)


#https://www.kaggle.com/code/davids1992/specaugment-quick-implementation
def spec_augment(spec: np.ndarray, num_mask=2, 
                 freq_masking_max_percentage=0.15, time_masking_max_percentage=0.25):

    spec = spec.copy()
    for i in range(num_mask):
        all_frames_num, all_freqs_num = spec.shape
        freq_percentage = random.uniform(0.0, freq_masking_max_percentage)
        
        num_freqs_to_mask = int(freq_percentage * all_freqs_num)
        f0 = np.random.uniform(low=0.0, high=all_freqs_num - num_freqs_to_mask)
        f0 = int(f0)
        spec[:, f0:f0 + num_freqs_to_mask] = 0

        time_percentage = random.uniform(0.0, time_masking_max_percentage)
        
        num_frames_to_mask = int(time_percentage * all_frames_num)
        t0 = np.random.uniform(low=0.0, high=all_frames_num - num_frames_to_mask)
        t0 = int(t0)
        spec[t0:t0 + num_frames_to_mask, :] = 0
    
    return spec
