import argparse
import re
import os, glob, datetime
import numpy as np
from keras.layers import Input, Conv2D, BatchNormalization, Activation, Subtract
from keras.models import Model, load_model
from keras.callbacks import CSVLogger, ModelCheckpoint, LearningRateScheduler, EarlyStopping
from keras.optimizers import Adam
import keras_implementation.utilities.data_generator as data_generator
import keras_implementation.utilities.logger as logger
import keras_implementation.utilities.image_utils as image_utils
import keras.backend as K
import cv2

import tensorflow as tf

# Allow memory growth in order to fix a Tensorflow bug
physical_devices = tf.config.list_physical_devices('GPU')

# This makes sure that at runtime, the initialization of the CUDA device physical_devices[0] (The only GPU in
# the system) will not allocate ALL of the memory on that device.
tf.config.experimental.set_memory_growth(physical_devices[0], True)

# Params
parser = argparse.ArgumentParser()
parser.add_argument('--model', default='MyDnCNN', type=str, help='choose a type of model')
parser.add_argument('--batch_size', default=128, type=int, help='batch size')
parser.add_argument('--train_data', default='data/Volume1/train', type=str, help='path of train data')
parser.add_argument('--val_data', default='data/Volume1/val', type=str, help='path of val data')
parser.add_argument('--sigma', default=25, type=int, help='noise level')
parser.add_argument('--epoch', default=300, type=int, help='number of train epoches')
parser.add_argument('--lr', default=1e-3, type=float, help='initial learning rate for Adam')
parser.add_argument('--save_every', default=1000, type=int, help='save model at after seeing x batches')
args = parser.parse_args()

save_dir = os.path.join('/home/ubuntu/PycharmProjects/MyDenoiser/keras_implementation',
                        'models',
                        args.model)

# Create the <save_dir> folder if it doesn't exist already
if not os.path.exists(save_dir):
    os.mkdir(save_dir)


def MyDnCNN(depth, filters=64, image_channels=1, use_batchnorm=True):
    """
    Complete implementation of MyDnCNN, a residual network using the Keras API.
    MyDnCNN is originally derived from DnCNN, but with some changes and
    reorganization

    :param depth: The total number of layers for the network, colloquially referred to
                    as the "depth" of the network
    :param filters: The total number of convolutional kernels in each convolutional
                    layer of the network
    :param image_channels: The number of dimensions of the input images, i.e.
                            image_channels=1 for grayscale images, or image_channels=3
                            for RGB images.
    :param use_batchnorm: Whether or not the layers of the network should use batch
                            normalization
    :return: A MyDnCNN model, defined using the Keras API
    """

    # Initialize counter to keep track of current layer
    layer_index = 0

    # Define Layer 0 -- The input layer, and increment layer_index
    input_layer = Input(shape=(None, None, image_channels), name='Input' + str(layer_index))
    layer_index += 1

    # Define Layer 1 -- Convolutional Layer + ReLU activation function, and increment layer_index
    x = Conv2D(filters=filters, kernel_size=(3, 3), strides=(1, 1), kernel_initializer='Orthogonal', padding='same',
               name='Conv' + str(layer_index))(input_layer)
    layer_index += 1
    x = Activation('relu', name='ReLU' + str(layer_index))(x)

    # Iterate through the rest of the (depth - 2) layers -- Convolutional Layer + (Maybe) BatchNorm layer + ReLU
    for i in range(depth - 2):

        # Define Convolutional Layer
        layer_index += 1
        x = Conv2D(filters=filters, kernel_size=(3, 3), strides=(1, 1), kernel_initializer='Orthogonal', padding='same',
                   use_bias=False, name='Conv' + str(layer_index))(x)

        # (Optionally) Define BatchNormalization layer
        if use_batchnorm:
            layer_index += 1
            x = BatchNormalization(axis=3, momentum=0.0, epsilon=0.0001, name='BatchNorm' + str(layer_index))(x)

        # Define ReLU Activation Layer
        layer_index += 1
        x = Activation('relu', name='ReLU' + str(layer_index))(x)

    # Define last layer -- Convolutional Layer and Subtraction Layer (input - noise)
    layer_index += 1
    x = Conv2D(filters=image_channels, kernel_size=(3, 3), strides=(1, 1), kernel_initializer='Orthogonal',
               padding='same',
               use_bias=False, name='Conv' + str(layer_index))(x)
    layer_index += 1
    x = Subtract(name='Subtract' + str(layer_index))([input_layer, x])

    # Finally, define the model
    model = Model(inputs=input_layer, outputs=x)

    return model


def findLastCheckpoint(save_dir):
    """
    Finds the most recent Model checkpoint files

    :param save_dir:
    :return:
    """
    file_list = glob.glob(os.path.join(save_dir, 'model_*.hdf5'))  # get name list of all .hdf5 files
    # file_list = os.listdir(save_dir)
    if file_list:
        epochs_exist = []
        for file_ in file_list:
            result = re.findall(".*model_(.*).hdf5.*", file_)
            # print(result[0])
            epochs_exist.append(int(result[0]))
        initial_epoch = max(epochs_exist)
    else:
        initial_epoch = 0
    return initial_epoch


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
        lr = initial_lr / 10
    elif epoch <= 80:
        lr = initial_lr / 20
    else:
        lr = initial_lr / 20
    logger.log('current learning rate is %2.8f' % lr)
    return lr


def gaussian_noise_train_datagen(epoch_iter=2000, epoch_num=5, batch_size=128, data_dir=args.train_data):
    """
    Generator function which yields training data where a "clear" image is obtained from
    data_dir, and a "blurry" image is obtained by adding gaussian noise to the "clear" imagef

    :param epoch_iter: The number of iterations per epoch
    :type epoch_iter: int
    :param epoch_num: The total number of epochs
    :type epoch_num: int
    :param batch_size: The number of training samplesused per iteration
    :type batch_size: int
    :param data_dir: The directory in which our training examples are located
    :type data_dir: str

    :return: Yields a blurry image "y" and a clear image "x"
    """

    while True:
        n_count = 0
        if n_count == 0:
            # print(n_count)
            print(f'Accessing training data in: {data_dir}')
            xs = data_generator.data_generator(data_dir)
            assert len(xs) % args.batch_size == 0, \
                logger.log(
                    'make sure the last iteration has a full batchsize, '
                    'this is important if you use batch normalization!')
            xs = xs.astype('float32') / 255.0
            indices = list(range(xs.shape[0]))
            n_count = 1
        for _ in range(epoch_num):
            np.random.shuffle(indices)  # shuffle
            for i in range(0, len(indices), batch_size):
                batch_x = xs[indices[i:i + batch_size]]
                noise = np.random.normal(0, args.sigma / 255.0, batch_x.shape)  # noise
                # noise =  K.random_normal(ge_batch_y.shape, mean=0, stddev=args.sigma/255.0)
                batch_y = batch_x + noise
                yield batch_y, batch_x


def my_train_datagen(epoch_iter=2000, num_epochs=5, batch_size=128, data_dir=args.train_data):
    """
    Generator function that yields training data samples from a specified data directory

    :param epoch_iter: The number of iterations per epoch
    :param num_epochs: The total number of epochs
    :param batch_size: The number of training examples for each training iteration
    :param data_dir: The directory in which training examples are stored
    :return: Yields a training example x and noisey image y
    """
    # Loop the following indefinitely...
    while True:
        # Set a counter variable
        counter = 0

        # If this is the first iteration...
        if counter == 0:
            print(f'Accessing training data in: {data_dir}')

            # Get training examples from data_dir using data_generator
            x_original = data_generator.data_generator(data_dir, image_type=data_generator.ImageType.CLEARIMAGE)
            y_original = data_generator.data_generator(data_dir, image_type=data_generator.ImageType.BLURRYIMAGE)

            # Assert that the last iteration has a full batch size
            assert len(x_original) % args.batch_size == 0, \
                logger.log(
                    'make sure the last iteration has a full batchsize, '
                    'this is important if you use batch normalization!')
            assert len(y_original) % args.batch_size == 0, \
                logger.log(
                    'make sure the last iteration has a full batchsize, '
                    'this is important if you use batch normalization!')

            # Standardize x and y to have a mean of 0 and standard deviation of 1
            # NOTE: x and y px values are centered at 0, meaning there are negative px values. We might have trouble
            # visualizing px that aren't either from [0, 255] or [0, 1], so just watch out for that
            x, x_orig_mean, x_orig_std = image_utils.standardize(x_original)
            y, y_orig_mean, y_orig_std = image_utils.standardize(y_original)

            ''' Just logging 
            logger.print_numpy_statistics(x, "x (standardized)")
            logger.print_numpy_statistics(y, "y (standardized)")
            '''

            # Save the reversed standardization of x and y into variables
            x_reversed = image_utils.reverse_standardize(x, x_orig_mean, x_orig_std)
            y_reversed = image_utils.reverse_standardize(y, y_orig_mean, y_orig_std)

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


# define loss
def sum_squared_error(y_true, y_pred):
    # return K.mean(K.square(y_pred - y_true), axis=-1)
    # return K.sum(K.square(y_pred - y_true), axis=-1)/2
    return K.sum(K.square(y_pred - y_true)) / 2


def original_callbacks():
    """
    Creates a list of callbacks for the Model Training process.
    This is a copy of the list of callbacks used for the original DnCNN paper

    :return: List of callbacks
    :rtype: list
    """

    # noinspection PyListCreation
    callbacks = []

    # Add checkpoints every <save_every> # of iterations
    callbacks.append(ModelCheckpoint(os.path.join(save_dir, 'model_{epoch:03d}.hdf5'),
                                     verbose=1, save_weights_only=False, save_freq=args.save_every))

    # Add the ability to log training information to <save_dir>/log.csv
    callbacks.append(CSVLogger(os.path.join(save_dir, 'log.csv'), append=True, separator=','))

    # Add a Learning Rate Scheduler to dynamically change the learning rate over time
    callbacks.append(LearningRateScheduler(lr_schedule))

    return callbacks


def new_callbacks():
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
                                     verbose=1, save_weights_only=False, save_freq=args.save_every))

    # Add the ability to log training information to <save_dir>/log.csv
    callbacks.append(CSVLogger(os.path.join(save_dir, 'log.csv'), append=True, separator=','))

    # Add a Learning Rate Scheduler to dynamically change the learning rate over time
    callbacks.append(LearningRateScheduler(lr_schedule))

    # Add Early Stopping so that we stop training once val_loss stops decreasing after <patience> # of epochs
    callbacks.append(EarlyStopping(monitor='val_loss', mode='min', verbose=1, patience=3))

    return callbacks


def main():
    """
    Creates and trains the MyDenoiser Keras model.
    If no checkpoints exist, we will start from scratch.
    Otherwise, training will resume from previous checkpoints.

    :return: None
    """

    # Create a MyDnCNN model
    model = MyDnCNN(depth=17, filters=64, image_channels=1, use_batchnorm=True)
    model.summary()

    # Load the last model
    initial_epoch = findLastCheckpoint(save_dir=save_dir)
    if initial_epoch > 0:
        print('resuming by loading epoch %03d' % initial_epoch)
        model = load_model(os.path.join(save_dir, 'model_%03d.hdf5' % initial_epoch), compile=False)

    # compile the model
    model.compile(optimizer=Adam(0.001), loss=sum_squared_error)

    # Train the model
    history = model.fit(my_train_datagen(batch_size=args.batch_size, data_dir=args.train_data),
                        steps_per_epoch=2000,
                        epochs=args.epoch,
                        verbose=1,
                        initial_epoch=initial_epoch,
                        callbacks=new_callbacks(),
                        )


if __name__ == '__main__':
    # Run the main function
    main()