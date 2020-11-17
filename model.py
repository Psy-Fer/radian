from tcn import TCN

import tensorflow as tf
from tensorflow import Variable
from tensorflow.keras import Input, Model, backend
from tensorflow.keras.backend import ctc_batch_cost, get_value, set_value
from tensorflow.keras.layers import Dense, Activation, Lambda
from tensorflow.keras.models import load_model
from tensorflow.keras.optimizers import Adam
from tensorflow.keras.optimizers.schedules import PiecewiseConstantDecay

# Computed elsewhere
MAX_LABEL_LEN = 46

def initialise_or_load_model(checkpoint, epoch_to_resume, config):
    if checkpoint is not None:
        model = restore_checkpoint(checkpoint, config, MAX_LABEL_LEN)
        update_learning_rate(model, config.train.opt.lr)
        initial_epoch = epoch_to_resume
    else:
        model = initialise_model(config, MAX_LABEL_LEN)
        initial_epoch = 0
    return model, initial_epoch

def initialise_model(config, max_label_len):
    model = build_model(config.model, max_label_len, train=True)
    optimizer = get_optimizer(config.train.opt)
    model.compile(optimizer = optimizer,
                  loss = {'ctc': lambda labels, y_pred: y_pred})
    return model

def restore_checkpoint(checkpoint, config, max_label_len):
    model = build_model(config.model, max_label_len, train=True)
    model.load_weights(checkpoint)
    print("Loaded checkpoint {0}".format(checkpoint))
    return model

def build_model(config, max_label_len, train=True):
    c = config
    input_shape = (c.timesteps, 1)

    inputs = Input(shape=input_shape, name="inputs") # (None, 512, 1)

    params = {'nb_filters': c.tcn.nb_filters,
              'kernel_size': c.tcn.kernel_size,
              'nb_stacks': c.tcn.nb_stacks,
              'dilations': c.tcn.dilations,
              'padding': c.tcn.padding,
              'use_skip_connections': c.tcn.use_skip_connections,
              'dropout_rate': c.tcn.dropout_rate,
              'return_sequences': c.tcn.return_sequences,
              'activation': c.tcn.activation,
              'kernel_initializer': c.tcn.kernel_initializer,
              'use_batch_norm': c.tcn.use_batch_norm,
              }

    inner = TCN(**params)(inputs)   # (None, 512, 64)
    inner = Dense(c.relu_units)(inner) # (None, 512, 5)
    inner = Activation('relu')(inner)
    inner = Dense(c.softmax_units)(inner) # (None, 512, 5)
    y_pred = Activation('softmax')(inner) # (None, 512, 5)

    labels = Input(shape=(max_label_len,), name="labels") # (None, 39)
    input_length = Input(shape=[1],name="input_length") # (None, 1)
    label_length = Input(shape=[1],name="label_length") # (None, 1)

    loss_out = Lambda(
        ctc_loss_lambda, output_shape=(1,), name='ctc')((
            y_pred, labels, input_length, label_length))

    if train == True:
        return Model(inputs=[inputs, labels, input_length, label_length],
                     outputs=[loss_out])
    else:
        return Model(inputs=[inputs], outputs=y_pred)  

def ctc_loss_lambda(args):
    """
    This function is required because Keras currently doesn't support
    loss functions with additional parameters so it needs to be
    implemented in a lambda layer.
    """
    y_pred, labels, input_length, label_length = args
    return ctc_batch_cost(labels, y_pred, input_length, label_length)

def get_optimizer(config):
    if config.use_cc_opt == True:
        return get_causalcall_optimizer(config.cc_opt)
    else:
        return Adam(learning_rate=config.lr)

def get_causalcall_optimizer(config):
    c = config
    step = Variable(0, trainable = False)
    boundaries = [int(c.max_steps * bound) for bound in c.boundaries]
    values = [c.init_rate * decay for decay in c.decays]
    learning_rate_fn = PiecewiseConstantDecay(boundaries, values)
    return Adam(learning_rate=learning_rate_fn(step))

def update_learning_rate(model, new_rate):
    print("Old learning rate: {}".format(get_value(model.optimizer.lr)))
    set_value(model.optimizer.lr, new_rate)
    print("New learning rate: {}".format(get_value(model.optimizer.lr)))
