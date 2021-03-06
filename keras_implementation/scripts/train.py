"""
Main script used to train HydraNet
"""

from deprecated import deprecated
import argparse
import os

os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'  # Suppress TensorFlow logging (1)
import tensorflow as tf
import sys
import numpy as np
from skimage.metrics import peak_signal_noise_ratio
from tensorflow.keras.models import load_model
from tensorflow.keras.callbacks import CSVLogger, ModelCheckpoint, LearningRateScheduler, EarlyStopping
from tensorflow.keras.optimizers import Adam
import tensorflow.keras.backend as K
from typing import List
from utilities import data_generator, logger, model_functions, image_utils
from utilities.data_generator import NoiseLevel

'''GPU Settings for CUDA'''
### Option A: ###
# # Set specific memory limit for the GPU
# gpus = tf.config.experimental.list_physical_devices('GPU')
# if gpus:
#     try:
#         tf.config.experimental.set_virtual_device_configuration(gpus[0], [
#             tf.config.experimental.VirtualDeviceConfiguration(memory_limit=4096)])
#     except RuntimeError as e:
#         print(e)
#################
### Option B: ###
# # Allow memory growth for CUDA in order to fix a Tensorflow bug
# physical_devices = tf.config.experimental.list_physical_devices('GPU')
# tf.config.experimental.set_memory_growth(physical_devices[0], True)
#################

# Command-line parameters
parser = argparse.ArgumentParser()
parser.add_argument('--model', default='MyDnCNN', type=str, help='choose a type of model')
parser.add_argument('--batch_size', default=128, type=int, help='batch size')
parser.add_argument('--train_data', action='append', default=[], type=str, help='path of train data')
parser.add_argument('--val_data', default='data/subj5/val', type=str, help='path of val data')
parser.add_argument('--noise_level', default='all', type=str, help='Noise Level: Can be low, medium, high, or all')
parser.add_argument('--id_portion', default='low', type=str, help='Image ID Portion: Can be low, middle, or high')
parser.add_argument('--epoch', default=80, type=int, help='number of train epochs')
parser.add_argument('--lr', default=2e-3, type=float, help='initial learning rate for Adam')
parser.add_argument('--save_every', default=1, type=int, help='save model every x # of epochs')
parser.add_argument('--result_dir', default='', type=str, help='save directory for resultant model .hdf5 files')
parser.add_argument('--is_3d', default=False, type=bool, help='True if we wish to retrain a 3d denoiser')
parser.add_argument('--is_cleanup', default=False, type=bool, help='True if we wish to retrain a cleanup denoiser')
parser.add_argument('--is_left_middle_right', default=False, type=bool, help='True if we wish to retrain denoisers'
                                                                             'on left, middle, and right brain'
                                                                             'portions')
parser.add_argument('--clear_data', action='append', default=[], type=str, help='Clear data directories (only used '
                                                                                'when is_cleanup == True')
parser.add_argument('--blurry_data', action='append', default=[], type=str, help='Blurry data directories (only used '
                                                                                 'when is_cleanup == True')
args = parser.parse_args()

# Set the noise level to decide which model to train
if args.noise_level == 'low':
    noise_level = NoiseLevel.LOW
elif args.noise_level == 'medium':
    noise_level = NoiseLevel.MEDIUM
elif args.noise_level == 'high':
    noise_level = NoiseLevel.HIGH
elif args.noise_level == 'all':
    noise_level = NoiseLevel.ALL
else:
    sys.exit("noise_level must be 'low', 'medium', 'high', or 'all'. Try again!")

# Set the save directory of the trained model hdf5 file
if args.is_cleanup:
    save_dir = os.path.join(args.result_dir, args.model + '_' + 'cleanup')
elif args.is_left_middle_right:
    save_dir = os.path.join(args.result_dir, args.model + '_' + args.id_portion + '_id')
else:
    save_dir = os.path.join(args.result_dir, args.model + '_' + args.noise_level + '_noise')

# Create the <save_dir> folder if it doesn't exist already
if not os.path.exists(save_dir):
    os.mkdir(save_dir)


def lr_schedule(epoch):
    """
    Learning rate scheduler for tensorflow API

    :param epoch: The current epoch
    :type epoch: int
    :return: The Learning Rate
    :rtype: float
    """

    initial_lr = args.lr
    if epoch <= 30:
        lr = initial_lr
    elif epoch <= 60:
        lr = initial_lr / 5
    elif epoch <= 80:
        lr = initial_lr / 10
    else:
        lr = initial_lr / 20
    logger.log('current learning rate is %2.8f' % lr)
    return lr


def new_lr_schedule(epoch):
    """
    Learning rate scheduler for tensorflow API

    :param epoch: The current epoch
    :type epoch: int
    :return: The Learning Rate
    :rtype: float
    """

    initial_lr = args.lr
    if epoch <= 20:
        lr = initial_lr
    elif epoch <= 30:
        lr = initial_lr * 0.75
    elif epoch <= 40:
        lr = initial_lr * 0.5
    elif epoch <= 50:
        lr = initial_lr * 0.25
    else:
        lr = initial_lr * 0.15
    logger.log('current learning rate is %2.8f' % lr)
    return lr


def my_train_datagen_single_model(epoch_iter: int = 2000,
                                  num_epochs: int = 5,
                                  batch_size: int = 128,
                                  data_dir: List[str] = args.train_data,
                                  is_3d: bool = False):
    """
    Generator function that yields training data samples from a specified data directory.
    This is used to generate all patches at once regardless of the noise level.

    Parameters
    ----------
    epoch_iter: The number of iterations per epoch
    num_epochs: The total number of epochs
    batch_size: The number of training examples for each training iteration
    data_dir: The directory in which training examples are stored
    is_3d:

    Returns
    -------
    Yields a training example x and a noisy example y
    """
    # Make sure we don't have an empty set of data directories
    assert (len(data_dir)) > 0

    # Loop the following indefinitely...
    while True:
        # Set a counter variable
        counter = 0

        # If this is the first iteration...
        if counter == 0:
            print(f'Accessing training data in: {data_dir}')

            '''Load training data'''
            if is_3d:
                x, y = data_generator.pair_3d_data_generator(data_dir)
            else:
                if len(data_dir) == 1:
                    x, y = data_generator.pair_data_generator(data_dir[0])
                elif len(data_dir) > 1:
                    x, y = data_generator.pair_data_generator_multiple_data_dirs(data_dir)

            # Create lists to store all of the clear patches (x) and blurry patches (y)
            x_filtered = []
            y_filtered = []

            # Iterate over all of the image patches
            for x_patch, y_patch in zip(x, y):

                # If the patch is black (i.e. the max px value < 10), just skip this training example
                if np.max(x_patch) < 10:
                    continue

                # Add x_patch and y_patch to the list
                x_filtered.append(x_patch)
                y_filtered.append(y_patch)

            # Convert image patches and stds into numpy arrays
            x_filtered = np.array(x_filtered, dtype='uint8')
            y_filtered = np.array(y_filtered, dtype='uint8')

            # Remove elements from x_filtered and y_filtered so thatthey has the right number of patches
            discard_n = len(x_filtered) - len(y_filtered) // batch_size * batch_size;
            x_filtered = np.delete(x_filtered, range(discard_n), axis=0)
            y_filtered = np.delete(y_filtered, range(discard_n), axis=0)

            # Assert that the last iteration has a full batch size
            assert len(x_filtered) % args.batch_size == 0, \
                logger.log(
                    'make sure the last iteration has a full batchsize, '
                    'this is important if you use batch normalization!')
            assert len(y_filtered) % args.batch_size == 0, \
                logger.log(
                    'make sure the last iteration has a full batchsize, '
                    'this is important if you use batch normalization!')

            # Standardize x and y to have a mean of 0 and standard deviation of 1
            # NOTE: x and y px values are centered at 0, meaning there are negative px values. Most libraries have
            # trouble visualizing px that aren't either from [0, 255] or [0, 1], so watch out for that
            x_filtered, x_orig_mean, x_orig_std = image_utils.standardize(x_filtered)
            y_filtered, y_orig_mean, y_orig_std = image_utils.standardize(y_filtered)

            '''Just for logging
            # Save the reversed standardization of x and y into variables
            x_reversed = image_utils.reverse_standardize(x, x_orig_mean, x_orig_std)
            y_reversed = image_utils.reverse_standardize(y, y_orig_mean, y_orig_std)
            '''

            # Get a list of indices, from 0 to the total number of training examples
            indices = list(range(x_filtered.shape[0]))

            # Make sure that x and y have the same number of training examples
            assert indices == list(range(y_filtered.shape[0])), logger.log(
                'Make sure x and y are paired up properly! That is, x'
                'is a ClearImage, and y is a CoregisteredBlurryImage'
                'but that the two frames match eachother. ')

            # Increment the counter
            counter = 1

        # Iterate over the number of epochs
        for _ in range(num_epochs):

            # Shuffle the indices of the training examples
            np.random.shuffle(indices)

            # Iterate over the entire training set, skipping "batch_size" at a time
            for i in range(0, len(indices), batch_size):
                # Get the batch_x (clear) and batch_y (blurry)
                batch_x = x_filtered[indices[i:i + batch_size]]
                batch_y = y_filtered[indices[i:i + batch_size]]

                '''Just logging 
                # Get equivalently indexed batches from x_original, x_reversed, y_original, and y_reversed
                batch_x_reversed = x_reversed[indices[i:i + batch_size]]
                batch_y_reversed = y_reversed[indices[i:i + batch_size]]
                
                # Show some images from this batch
                logger.show_images(images=[("batch_x[0]", batch_x[0]),
                                         ("batch_x_reversed[0]", batch_x_reversed[0]),
                                         ("batch_y[0]", batch_y[0]),
                                         ("batch_y_reversed[0]", batch_y_reversed[0])])
                '''

                # Finally, yield x and y, as this function is a generator
                yield batch_y, batch_x


def my_cleanup_train_datagen(num_epochs: int = 5, batch_size: int = 8, clear_data: List[str] = args.clear_data,
                             blurry_data: List[str] = args.blurry_data):
    """
    Generator function that yields training data from a specified directory.
    NOTE: This function does not split up data into patches. It yields entire images.

    Parameters
    ----------
    num_epochs: The total number of epochs
    batch_size: The number of training examples for each training iteration
    clear_data: The directory in which clear images are stored
    blurry_data: The directory in which blurry images are stored

    Yields
    ------
    Training images
    """
    while True:
        counter = 0

        # If this is the first iteration...
        if counter == 0:
            print(f'Accessing: \n\n- Clear training data in: {clear_data}\n- Blurry training data in: {blurry_data}')

            x_original, y_original = data_generator.cleanup_data_generator(clear_image_dirs=clear_data,
                                                                           blurry_image_dirs=blurry_data)

            ''' Just logging 
            logger.show_images([("x_original", x_original),
                                ("y_original", y_original)])
            '''

            # Convert image patches and stds into numpy arrays
            x_filtered = np.array(x_original, dtype='uint8')
            y_filtered = np.array(y_original, dtype='uint8')

            # Remove elements from x_filtered and y_filtered so that they has the right number of patches
            discard_n = len(x_filtered) - len(x_filtered) // batch_size * batch_size;
            print(f'discard_n ={discard_n}')
            x_filtered = np.delete(x_filtered, range(discard_n), axis=0)
            y_filtered = np.delete(y_filtered, range(discard_n), axis=0)

            print(f'The length of x_filtered: {len(x_filtered)}')
            print(f'The length of y_filtered: {len(y_filtered)}')

            # Assert that the last iteration has a full batch size
            assert len(x_filtered) % args.batch_size == 0, \
                logger.log(
                    'make sure the last iteration has a full batchsize, '
                    'this is important if you use batch normalization!')
            assert len(y_filtered) % args.batch_size == 0, \
                logger.log(
                    'make sure the last iteration has a full batchsize, '
                    'this is important if you use batch normalization!')

            # Standardize x and y to have a mean of 0 and standard deviation of 1
            # NOTE: x and y px values are centered at 0, meaning there are negative px values. We might have trouble
            # visualizing px that aren't either from [0, 255] or [0, 1], so just watch out for that
            x, x_orig_mean, x_orig_std = image_utils.standardize(x_filtered)
            y, y_orig_mean, y_orig_std = image_utils.standardize(y_filtered)

            ''' Just logging 
            logger.print_numpy_statistics(x, "x (standardized)")
            logger.print_numpy_statistics(y, "y (standardized)")
            '''

            '''Just for logging
            # Save the reversed standardization of x and y into variables
            x_reversed = image_utils.reverse_standardize(x, x_orig_mean, x_orig_std)
            y_reversed = image_utils.reverse_standardize(y, y_orig_mean, y_orig_std)
            '''

            # Get a list of indices, from 0 to the total number of training examples
            indices = list(range(x.shape[0]))

            # Make sure that x and y have the same number of training examples
            assert indices == list(range(y.shape[0])), logger.log('Make sure x and y are paired up properly! That is, x'
                                                                  'is a ClearImage, and y is a CoregisteredBlurryImage'
                                                                  'but that the two frames match eachother. ')

            # Increment the counter
            counter += 1

        # Iterate over the number of epochs
        for _ in range(num_epochs):

            # Shuffle the indices of the training examples
            np.random.shuffle(indices)

            # Iterate over the entire training set, skipping "batch_size" at a time
            for i in range(0, len(indices), batch_size):
                # Get the batch_x (clear) and batch_y (blurry)
                batch_x = x[indices[i:i + batch_size]]
                batch_y = y[indices[i:i + batch_size]]

                '''Just logging
                # Get equivalently indexed batches from x_original, x_reversed, y_original, and y_reversed
                batch_x_original = x_original[indices[i:i + batch_size]]
                batch_x_reversed = x_reversed[indices[i:i + batch_size]]
                batch_y_original = y_original[indices[i:i + batch_size]]
                batch_y_reversed = y_reversed[indices[i:i + batch_size]]

                # Show some images from this batch
                logger.show_images(images=[("batch_x[0]", batch_x[0]),
                                         ("batch_x_original[0]", batch_x_original[0]),
                                         ("batch_x_reversed[0]", batch_x_reversed[0]),
                                         ("batch_y[0]", batch_y[0]),
                                         ("batch_y_original[0]", batch_y_original[0]),
                                         ("batch_y_reversed[0]", batch_y_reversed[0])])
                '''

                # Finally, yield x and y, as this function is a generator
                yield batch_y, batch_x


def my_train_datagen(epoch_iter=2000,
                     num_epochs=5,
                     batch_size=128,
                     data_dir=args.train_data,
                     noise_level=NoiseLevel.LOW,
                     low_noise_threshold=0.28,
                     high_noise_threshold=0.07):
    """
    Generator function that yields training data samples from a specified data directory

    :param epoch_iter: The number of iterations per epoch
    :param num_epochs: The total number of epochs
    :param batch_size: The number of training examples for each training iteration
    :param data_dir: The directory in which training examples are stored
    :param noise_level: The level of noise of the training data that we want
    :type noise_level: NoiseLevel
    :param low_noise_threshold: The lower residual image standard deviation threshold used to determine which data
                                should go to which network
    :type low_noise_threshold: float
    :param high_noise_threshold: The upper residual image standard deviation threshold used to determine which data
                                should go to which network
    :type high_noise_threshold: float

    :return: Yields a training example x and noisy image y
    """
    while True:
        counter = 0

        # If this is the first iteration...
        if counter == 0:
            print(f'Accessing training data in: {data_dir}')

            # If we are getting train data from one directory...
            if len(data_dir) == 1:
                # Get training examples from data_dir[0] using pair_data_generator
                x_original, y_original = data_generator.pair_data_generator(data_dir[0])

            # Else, if we're getting data from multiple directories...
            elif len(data_dir) > 1:
                # Get training examples from data_dir using pair_data_generator_multiple_data_dirs
                x_original, y_original = data_generator.pair_data_generator_multiple_data_dirs(data_dir)

            # Else, something is wrong - we don't have train data! Exit.
            else:
                sys.exit('ERROR: You didn\'t provide any data directories to train on!')

            ''' Just logging 
            logger.show_images([("x_original", x_original),
                                ("y_original", y_original)])
            '''

            # Create lists to store all of the patches and stds for each noise level category
            x_low_noise = []
            y_low_noise = []
            stds_low_noise = []
            x_medium_noise = []
            y_medium_noise = []
            stds_medium_noise = []
            x_high_noise = []
            y_high_noise = []
            stds_high_noise = []
            x_all_noise = []
            y_all_noise = []
            stds_all_noise = []
            stds = []
            x_filtered = []
            y_filtered = []

            print(f'low_noise_threshold: {low_noise_threshold}')
            print(f'high_noise_threshold: {high_noise_threshold}')

            # Iterate over all of the image patches
            for x_patch, y_patch in zip(x_original, y_original):

                # If the patch is black (i.e. the max px value < 10), just skip this training example
                if np.max(x_patch) < 10:
                    continue

                # Get the residual std
                std = data_generator.get_residual_std(clear_patch=x_patch,
                                                      blurry_patch=y_patch)

                # Add the patches and their residual stds to their corresponding lists based on noise level
                x_all_noise.append(x_patch)
                y_all_noise.append(y_patch)
                stds_all_noise.append(x_patch)
                if std < low_noise_threshold:
                    x_low_noise.append(x_patch)
                    y_low_noise.append(y_patch)
                    stds_low_noise.append(std)
                    continue
                elif low_noise_threshold < std < high_noise_threshold:
                    x_medium_noise.append(x_patch)
                    y_medium_noise.append(y_patch)
                    stds_medium_noise.append(std)
                    continue
                elif std > high_noise_threshold:
                    x_high_noise.append(x_patch)
                    y_high_noise.append(y_patch)
                    stds_high_noise.append(std)
                    continue
                x_all_noise.append(x_patch)
                y_all_noise.append(y_patch)
                stds_all_noise.append(x_patch)

            # Get x_filtered based upon the noise level that we're looking for
            if noise_level == NoiseLevel.LOW:
                print('Setting filtered data lists to low noise lists')
                print(f'Length of x_low_noise: {len(x_low_noise)}')
                print(f'Length of y_low_noise: {len(y_low_noise)}')
                x_filtered = x_low_noise
                y_filtered = y_low_noise
                stds = stds_low_noise
            elif noise_level == NoiseLevel.MEDIUM:
                print('Setting filtered data lists to medium noise lists')
                print(f'Length of x_medium_noise: {len(x_medium_noise)}')
                print(f'Length of y_medium_noise: {len(y_medium_noise)}')
                x_filtered = x_medium_noise
                y_filtered = y_medium_noise
                stds = stds_medium_noise
            elif noise_level == NoiseLevel.HIGH:
                print('Setting filtered data lists to high noise lists')
                print(f'Length of x_high_noise: {len(x_high_noise)}')
                print(f'Length of y_high_noise: {len(y_high_noise)}')
                x_filtered = x_high_noise
                y_filtered = y_high_noise
                stds = stds_high_noise
            elif noise_level == NoiseLevel.ALL:
                x_filtered = x_all_noise
                y_filtered = y_all_noise
                stds = stds_high_noise

            # Convert image patches and stds into numpy arrays
            x_filtered = np.array(x_filtered, dtype='uint8')
            y_filtered = np.array(y_filtered, dtype='uint8')
            stds = np.array(stds, dtype='float64')

            # Remove elements from x_filtered and y_filtered so that they has the right number of patches
            discard_n = len(x_filtered) - len(x_filtered) // batch_size * batch_size;
            print(f'discard_n ={discard_n}')
            x_filtered = np.delete(x_filtered, range(discard_n), axis=0)
            y_filtered = np.delete(y_filtered, range(discard_n), axis=0)

            ''' Just logging
            # Plot the residual standard deviation
            image_utils.plot_standard_deviations(stds)
            '''

            print(f'The length of x_filtered: {len(x_filtered)}')
            print(f'The length of y_filtered: {len(y_filtered)}')

            # Assert that the last iteration has a full batch size
            assert len(x_filtered) % args.batch_size == 0, \
                logger.log(
                    'make sure the last iteration has a full batchsize, '
                    'this is important if you use batch normalization!')
            assert len(y_filtered) % args.batch_size == 0, \
                logger.log(
                    'make sure the last iteration has a full batchsize, '
                    'this is important if you use batch normalization!')

            # Standardize x and y to have a mean of 0 and standard deviation of 1
            # NOTE: x and y px values are centered at 0, meaning there are negative px values. We might have trouble
            # visualizing px that aren't either from [0, 255] or [0, 1], so just watch out for that
            x, x_orig_mean, x_orig_std = image_utils.standardize(x_filtered)
            y, y_orig_mean, y_orig_std = image_utils.standardize(y_filtered)

            ''' Just logging 
            logger.print_numpy_statistics(x, "x (standardized)")
            logger.print_numpy_statistics(y, "y (standardized)")
            '''

            '''Just for logging
            # Save the reversed standardization of x and y into variables
            x_reversed = image_utils.reverse_standardize(x, x_orig_mean, x_orig_std)
            y_reversed = image_utils.reverse_standardize(y, y_orig_mean, y_orig_std)
            '''

            # Get a list of indices, from 0 to the total number of training examples
            indices = list(range(x.shape[0]))

            # Make sure that x and y have the same number of training examples
            assert indices == list(range(y.shape[0])), logger.log('Make sure x and y are paired up properly! That is, x'
                                                                  'is a ClearImage, and y is a CoregisteredBlurryImage'
                                                                  'but that the two frames match eachother. ')

            # Increment the counter
            counter += 1

        # Iterate over the number of epochs
        for _ in range(num_epochs):

            # Shuffle the indices of the training examples
            np.random.shuffle(indices)

            # Iterate over the entire training set, skipping "batch_size" at a time
            for i in range(0, len(indices), batch_size):
                # Get the batch_x (clear) and batch_y (blurry)
                batch_x = x[indices[i:i + batch_size]]
                batch_y = y[indices[i:i + batch_size]]

                '''Just logging
                # Get equivalently indexed batches from x_original, x_reversed, y_original, and y_reversed
                batch_x_original = x_original[indices[i:i + batch_size]]
                batch_x_reversed = x_reversed[indices[i:i + batch_size]]
                batch_y_original = y_original[indices[i:i + batch_size]]
                batch_y_reversed = y_reversed[indices[i:i + batch_size]]

                # Show some images from this batch
                logger.show_images(images=[("batch_x[0]", batch_x[0]),
                                         ("batch_x_original[0]", batch_x_original[0]),
                                         ("batch_x_reversed[0]", batch_x_reversed[0]),
                                         ("batch_y[0]", batch_y[0]),
                                         ("batch_y_original[0]", batch_y_original[0]),
                                         ("batch_y_reversed[0]", batch_y_reversed[0])])
                '''

                # Finally, yield x and y, as this function is a generator
                yield batch_y, batch_x


def my_train_datagen_left_middle_right(num_epochs=5,
                                       batch_size=128,
                                       data_dir=args.train_data,
                                       low_image_id: int = 34,
                                       high_image_id: int = 100):
    """
    Generator function that yields training data samples from a specified data directory.

    Only returns images with an image id between low_image_id and high_image_id

    Parameters
    ----------
    num_epochs: The total number of epochs
    batch_size: The number of training examples for each training iteration
    data_dir: The directory in which training examples are stored
    low_image_id: The lower id threshold for returning images
    high_image_id: The upper id threshold for returning images

    Returns
    -------
    Yields a training example x and noisy image y
    """
    # Loop the following indefinitely...
    while True:
        counter = 0

        # If this is the first iteration...
        if counter == 0:
            print(f'Accessing training data in: {data_dir}')

            # Get our train data
            x_original, y_original = data_generator.pair_data_generator(data_dir, use_image_id_range=True,
                                                                        low_image_id=low_image_id,
                                                                        high_image_id=high_image_id)

            x_filtered = []
            y_filtered = []

            # Remove pure black patches
            for x_patch, y_patch in zip(x_original, y_original):
                if np.max(x_patch) < 10:
                    continue
                x_patch = x_patch.reshape(x_patch.shape[0], x_patch.shape[1])
                y_patch = y_patch.reshape(y_patch.shape[0], y_patch.shape[1])
                x_filtered.append(x_patch)
                y_filtered.append(y_patch)

            # Convert image patches and stds into numpy arrays
            x_filtered = np.array(x_filtered, dtype='uint8')
            y_filtered = np.array(y_filtered, dtype='uint8')

            # Remove elements from x_filtered and y_filtered so that they have the right number of patches
            discard_n = len(x_filtered) - len(x_filtered) // batch_size * batch_size
            print(f'discard_n = {discard_n}')
            x_filtered = np.delete(x_filtered, range(discard_n), axis=0)
            y_filtered = np.delete(y_filtered, range(discard_n), axis=0)

            print(f'The length of x_filtered: {len(x_filtered)}')
            print(f'The length of y_filtered: {len(y_filtered)}')

            # Assert that the last iteration has a full batch size
            assert len(x_filtered) % args.batch_size == 0, \
                logger.log(
                    'make sure the last iteration has a full batchsize, '
                    'this is important if you use batch normalization!')
            assert len(y_filtered) % args.batch_size == 0, \
                logger.log(
                    'make sure the last iteration has a full batchsize, '
                    'this is important if you use batch normalization!')
            assert len(x_filtered) == len(y_filtered), logger.log('Make sure x and y are paired up properly!')

            # Standardize x and y to have a mean of 0 and standard deviation of 1
            x, x_orig_mean, x_orig_std = image_utils.standardize(x_filtered)
            y, y_orig_mean, y_orig_std = image_utils.standardize(y_filtered)

            # Get a list of indices, from 0 to the total number of training examples
            indices = list(range(x.shape[0]))

            counter += 1

        # Iterate over the number of epochs
        for _ in range(num_epochs):

            # Shuffle the indices of the training examples
            np.random.shuffle(indices)

            # Iterate over the entire training set, skipping "batch_size" at a time
            for i in range(0, len(indices), batch_size):
                # Get the batch_x (clear) and batch_y (blurry)
                batch_x = x[indices[i:i + batch_size]]
                batch_y = y[indices[i:i + batch_size]]

                # Finally, yield x and y, as this function is a generator
                yield batch_y, batch_x


def my_train_datagen_estimated_with_psnr(num_epochs=5,
                                         batch_size=128,
                                         data_dir=args.train_data,
                                         low_psnr_threshold: float = 0.28,
                                         high_psnr_threshold: float = 0.07):
    """
    Generator function that yields training data samples from a specified data directory

    :param num_epochs: The total number of epochs
    :param batch_size: The number of training examples for each training iteration
    :param data_dir: The directory in which training examples are stored
    :param low_psnr_threshold: The lower PSNR threshold to keep an image patch pair
    :param high_psnr_threshold: The upper PSNR threshold to keep an image patch pair

    :return: Yields a training example x and noisy image y
    """
    # Loop the following indefinitely...
    while True:
        counter = 0

        # If this is the first iteration...
        if counter == 0:
            print(f'Accessing training data in: {data_dir}')

            ''' TODO: Remove this, it's old and is replaced by a single line below.
            # Get our train data
            if len(data_dir) == 1:
                x_original, y_original = data_generator.pair_data_generator(data_dir[0])
            elif len(data_dir) > 1:
                x_original, y_original = data_generator.pair_data_generator_multiple_data_dirs(data_dir)
            else:
                sys.exit('ERROR: You didn\'t provide any data directories to train on!')
            '''

            # Get our train data
            x_original, y_original = data_generator.pair_data_generator(data_dir)

            x_filtered = []
            y_filtered = []

            # Iterate over all of the image patches
            for x_patch, y_patch in zip(x_original, y_original):
                if np.max(x_patch) < 10:
                    continue
                x_patch = x_patch.reshape(x_patch.shape[0], x_patch.shape[1])
                y_patch = y_patch.reshape(y_patch.shape[0], y_patch.shape[1])
                psnr = peak_signal_noise_ratio(x_patch, y_patch)

                if low_psnr_threshold < psnr < high_psnr_threshold:
                    x_filtered.append(x_patch)
                    y_filtered.append(y_patch)

            # Convert image patches and stds into numpy arrays
            x_filtered = np.array(x_filtered, dtype='uint8')
            y_filtered = np.array(y_filtered, dtype='uint8')

            # Remove elements from x_filtered and y_filtered so that they has the right number of patches
            discard_n = len(x_filtered) - len(x_filtered) // batch_size * batch_size
            print(f'discard_n ={discard_n}')
            x_filtered = np.delete(x_filtered, range(discard_n), axis=0)
            y_filtered = np.delete(y_filtered, range(discard_n), axis=0)

            print(f'The length of x_filtered: {len(x_filtered)}')
            print(f'The length of y_filtered: {len(y_filtered)}')

            # Assert that the last iteration has a full batch size
            assert len(x_filtered) % args.batch_size == 0, \
                logger.log(
                    'make sure the last iteration has a full batchsize, '
                    'this is important if you use batch normalization!')
            assert len(y_filtered) % args.batch_size == 0, \
                logger.log(
                    'make sure the last iteration has a full batchsize, '
                    'this is important if you use batch normalization!')
            assert len(x_filtered) == len(y_filtered), logger.log('Make sure x and y are paired up properly!')

            # Standardize x and y to have a mean of 0 and standard deviation of 1
            x, x_orig_mean, x_orig_std = image_utils.standardize(x_filtered)
            y, y_orig_mean, y_orig_std = image_utils.standardize(y_filtered)

            # Get a list of indices, from 0 to the total number of training examples
            indices = list(range(x.shape[0]))

            counter += 1

        # Iterate over the number of epochs
        for _ in range(num_epochs):

            # Shuffle the indices of the training examples
            np.random.shuffle(indices)

            # Iterate over the entire training set, skipping "batch_size" at a time
            for i in range(0, len(indices), batch_size):
                # Get the batch_x (clear) and batch_y (blurry)
                batch_x = x[indices[i:i + batch_size]]
                batch_y = y[indices[i:i + batch_size]]

                # Finally, yield x and y, as this function is a generator
                yield batch_y, batch_x


def sum_squared_error(y_true, y_pred):
    """
    Returns sum-squared error between y_true and y_pred.
    This is the loss function for the network

    :param y_true: Target
    :type y_true: numpy array
    :param y_pred: Prediction
    :type y_pred: numpy array

    :return: Sum-Squared Error between the two
    :rtype: float
    """
    return K.sum(K.square(y_pred - y_true)) / 2


def get_callbacks():
    """
    Creates a list of callbacks for the Model Training process.
    This is the new list of callbacks used for MyDenoiser

    :return: List of callbacks
    :rtype: list
    """

    # noinspection PyListCreation
    callbacks = []

    # Add checkpoints every <save_every> # of iterations
    callbacks.append(ModelCheckpoint(os.path.join(save_dir, 'model_{epoch:03d}.hdf5'),
                                     verbose=1, save_weights_only=False, period=args.save_every))

    # Add the ability to log training information to <save_dir>/log.csv
    callbacks.append(CSVLogger(os.path.join(save_dir, 'log.csv'), append=True, separator=','))

    # Add a Learning Rate Scheduler to dynamically change the learning rate over time
    callbacks.append(LearningRateScheduler(new_lr_schedule))

    # Add Early Stopping so that we stop training once val_loss stops decreasing after <patience> # of epochs
    # callbacks.append(EarlyStopping(monitor='val_loss', mode='min', verbose=1, patience=3))

    return callbacks


def train():
    """
    Creates and trains the MyDenoiser Keras model.
    If no checkpoints exist, we will start from scratch.
    Otherwise, training will resume from previous checkpoints.

    Returns
    -------
    None
    """

    # Select the type of model to use
    if args.model == 'MyDnCNN':
        # Create a MyDnCNN model
        model = model_functions.MyDnCNN(depth=17, filters=64, image_channels=1, use_batchnorm=True)
    elif args.model == 'MyDenoiser':
        # Create a MyDenoiser model
        model = model_functions.MyDenoiser()

    # Print a summary of the model
    model.summary()

    # Load the last model
    initial_epoch = model_functions.findLastCheckpoint(save_dir=save_dir)
    if initial_epoch > 0:
        print('resuming by loading epoch %03d' % initial_epoch)
        model = load_model(os.path.join(save_dir, 'model_%03d.hdf5' % initial_epoch), compile=False)

    # Compile the model
    model.compile(optimizer=Adam(0.001), loss=sum_squared_error)

    if noise_level == NoiseLevel.ALL:
        # Train the model on all noise levels
        history = model.fit(my_train_datagen_single_model(batch_size=args.batch_size,
                                                          data_dir=args.train_data),
                            steps_per_epoch=2000,
                            epochs=args.epoch,
                            initial_epoch=initial_epoch,
                            callbacks=get_callbacks())
    elif noise_level == NoiseLevel.LOW:
        # Train the model on the individual noise level
        history = model.fit(my_train_datagen_estimated_with_psnr(batch_size=args.batch_size,
                                                                 data_dir=args.train_data,
                                                                 low_psnr_threshold=30.0,
                                                                 high_psnr_threshold=100.0),
                            steps_per_epoch=2000,
                            epochs=args.epoch,
                            initial_epoch=initial_epoch,
                            callbacks=get_callbacks())
    elif noise_level == NoiseLevel.MEDIUM:
        # Train the model on the individual noise level
        history = model.fit(my_train_datagen_estimated_with_psnr(batch_size=args.batch_size,
                                                                 data_dir=args.train_data,
                                                                 low_psnr_threshold=15.0,
                                                                 high_psnr_threshold=40.0),
                            steps_per_epoch=2000,
                            epochs=args.epoch,
                            initial_epoch=initial_epoch,
                            callbacks=get_callbacks())
    elif noise_level == NoiseLevel.HIGH:
        # Train the model on the individual noise level
        history = model.fit(my_train_datagen_estimated_with_psnr(batch_size=args.batch_size,
                                                                 data_dir=args.train_data,
                                                                 low_psnr_threshold=0.0,
                                                                 high_psnr_threshold=30.0),
                            steps_per_epoch=2000,
                            epochs=args.epoch,
                            initial_epoch=initial_epoch,
                            callbacks=get_callbacks())


def train_left_middle_right():
    """
    Creates and trains the MyDenoiser Keras model.

    Trains separate residual_std_models for each of the left, middle, and right parts of the brain.

    If no checkpoints exist, we will start from scratch.
    Otherwise, training will resume from previous checkpoints.

    Returns
    -------
    None
    """

    # Select the type of model to use
    if args.model == 'MyDnCNN':
        # Create a MyDnCNN model
        model = model_functions.MyDnCNN(depth=17, filters=64, image_channels=1, use_batchnorm=True)
    elif args.model == 'MyDenoiser':
        # Create a MyDenoiser model
        model = model_functions.MyDenoiser()

    # Print a summary of the model
    model.summary()

    # Load the last model
    initial_epoch = model_functions.findLastCheckpoint(save_dir=save_dir)
    if initial_epoch > 0:
        print('resuming by loading epoch %03d' % initial_epoch)
        model = load_model(os.path.join(save_dir, 'model_%03d.hdf5' % initial_epoch), compile=False)

    # Compile the model
    model.compile(optimizer=Adam(0.001), loss=sum_squared_error)

    if args.id_portion == "low":
        # Train the model on the individual noise level
        history = model.fit(my_train_datagen_left_middle_right(batch_size=args.batch_size,
                                                               data_dir=args.train_data,
                                                               low_image_id=30,
                                                               high_image_id=100),
                            steps_per_epoch=2000,
                            epochs=args.epoch,
                            initial_epoch=initial_epoch,
                            callbacks=get_callbacks())
    elif args.id_portion == "middle":
        # Train the model on the individual noise level
        history = model.fit(my_train_datagen_left_middle_right(batch_size=args.batch_size,
                                                               data_dir=args.train_data,
                                                               low_image_id=60,
                                                               high_image_id=122),
                            steps_per_epoch=2000,
                            epochs=args.epoch,
                            initial_epoch=initial_epoch,
                            callbacks=get_callbacks())
    elif args.id_portion == "high":
        # Train the model on the individual noise level
        history = model.fit(my_train_datagen_left_middle_right(batch_size=args.batch_size,
                                                               data_dir=args.train_data,
                                                               low_image_id=60,
                                                               high_image_id=122),
                            steps_per_epoch=2000,
                            epochs=args.epoch,
                            initial_epoch=initial_epoch,
                            callbacks=get_callbacks())


def train_3d():
    """
    Creates and trains the My3dDenoiser TensorFlow model, a 3-dimensional Convolutional Denoiser.
    If no checkpoints exist, we will start from scratch.
    Otherwise, training will resume from previous checkpoints.

    Returns
    -------
    None
    """
    '''Load and initialize model'''
    model = model_functions.My3dDenoiser(depth=17, num_filters=64, use_batchnorm=True)
    # Print a summary of the model to the console
    model.summary()
    # Load the last model
    initial_epoch = model_functions.findLastCheckpoint(save_dir=save_dir)
    if initial_epoch > 0:
        print('resuming by loading epoch %03d' % initial_epoch)
        model = load_model(os.path.join(save_dir, 'model_%03d.hdf5' % initial_epoch), compile=False)
    # Compile the model
    model.compile(optimizer=Adam(0.001), loss=sum_squared_error)

    '''Train model'''
    history = model.fit(my_train_datagen_single_model(batch_size=args.batch_size,
                                                      data_dir=args.train_data, is_3d=True),
                        steps_per_epoch=2000,
                        epochs=args.epoch,
                        initial_epoch=initial_epoch,
                        callbacks=get_callbacks())


def train_cleanup_model():
    """
    Trains a model which takes entire patchwise-denoised images as input and outputs denoised image.

    Returns
    -------
    None
    """

    '''Load and initialize model'''
    model = model_functions.MyDnCNN(depth=17, filters=64, image_channels=1, use_batchnorm=True)
    # Print a summary of the model to the console
    model.summary()
    # Load the last model
    initial_epoch = model_functions.findLastCheckpoint(save_dir=save_dir)
    if initial_epoch > 0:
        print('resuming by loading epoch %03d' % initial_epoch)
        model = load_model(os.path.join(save_dir, 'model_%03d.hdf5' % initial_epoch), compile=False)
    # Compile the model
    model.compile(optimizer=Adam(0.001), loss=sum_squared_error)

    '''Train model'''
    history = model.fit(my_cleanup_train_datagen(batch_size=args.batch_size,
                                                 clear_data=args.clear_data, blurry_data=args.blurry_data),
                        steps_per_epoch=2000,
                        epochs=args.epoch,
                        initial_epoch=initial_epoch,
                        callbacks=get_callbacks())


if __name__ == '__main__':
    # Run the main function
    if args.is_3d:
        train_3d()
    elif args.is_left_middle_right:
        train_left_middle_right()
    elif args.is_cleanup:
        train_cleanup_model()
    else:
        train()
