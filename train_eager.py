import numpy as np
import tensorflow as tf
import os
import nets.Network as Segception
import utils.Loader as Loader
from utils.utils import get_params, preprocess, lr_decay, convert_to_tensors, restore_state, init_model, get_metrics
import argparse
from datetime import datetime

tf.random.set_seed(7)
np.random.seed(7)

# Quick global variables for loss curves etc...
train_losses_total, train_losses_model, train_losses_aux = [], [], []
n_epoch = []
test_accs, test_mious = [], []

# Trains the model for certains epochs on a dataset
def train(loader, model, epochs=15, batch_size=8, show_loss=True, augmenter=None, lr=None, init_lr=1e-4,
          saver=None, variables_to_optimize=None, evaluation=True, name_best_model = 'weights/best_own', preprocess_mode=None,
          n_test_samples_max=None):
    steps_per_epoch = (loader.n_train_samples // batch_size) + 1
    best_miou = 0

    for epoch in range(epochs):  # for each epoch
        lr_decay(lr, init_lr, 1e-9, epoch, epochs - 1)  # compute the new lr
        print('epoch: ' + str(epoch) + '. Learning rate: ' + str(lr.numpy()) + 'Total steps per epoch: ' + str(steps_per_epoch))

        total_loss, total_loss_m, total_loss_a = 0, 0, 0
        for step in range(int(steps_per_epoch)):  # for every batch
            with tf.GradientTape() as g:
                # get batch
                x, y, mask = loader.get_batch(size=batch_size, train=True, augmenter=augmenter)

                x = preprocess(x, mode=preprocess_mode)
                [x, y, mask] = convert_to_tensors([x, y, mask])

                y_, aux_y_ = model(x, training=True, aux_loss=True)  # get output of the model
                loss = tf.compat.v1.losses.softmax_cross_entropy(y, y_, weights=mask)  # compute loss

                total_loss_m += loss

                loss_aux = tf.compat.v1.losses.softmax_cross_entropy(y, aux_y_, weights=mask)  # compute loss
                total_loss_a += loss_aux
                loss = 1*loss + 0.8*loss_aux

                total_loss += loss

                if show_loss:
                    print('Training loss: ' + str(loss.numpy()))

            # Gets gradients and applies them
            grads = g.gradient(loss, variables_to_optimize)
            optimizer.apply_gradients(zip(grads, variables_to_optimize))

            # Log losses
            train_losses_total.append(total_loss.numpy())
            train_losses_model.append(total_loss_m.numpy())
            train_losses_aux.append(total_loss_a.numpy())
            n_epoch.append(epoch) # Log epoch for plotting later

        if evaluation:
            # get metrics
            #train_acc, train_miou = get_metrics(loader, model, loader.n_classes, train=True, preprocess_mode=preprocess_mode)
            test_acc, test_miou = get_metrics(loader, model, loader.n_classes, train=False, flip_inference=False, write_images=False,
                                              scales=[1], preprocess_mode=preprocess_mode, n_samples_max=n_test_samples_max)

            #print('Train accuracy: ' + str(train_acc.numpy()))
            #print('Train miou: ' + str(train_miou))
            print('Test accuracy: ' + str(test_acc.numpy()))
            print('Test miou: ' + str(test_miou))
            print('')

            test_accs.append(test_acc.numpy())
            test_mious.append(test_miou)

            # save model if best
            if test_miou > best_miou:
                best_miou = test_miou
                saver.save(None, name_best_model)
        else:
              saver.save(None,name_best_model)

        loader.suffle_segmentation()  # shuffle training set

    t = datetime.now().strftime("%Y-%m-%d-%H-%M-%S")

    # Hacky
    dat = np.array([np.array(x, dtype=float) for x in [train_losses_total, train_losses_aux, train_losses_model, n_epoch]])
    np.savetxt(t + '_train.txt', dat)

    dat = np.array([np.array(x, dtype=float) for x in [test_accs, test_mious]])
    np.savetxt(t + '_test.txt', dat)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", help="Dataset path", default='dataset')
    parser.add_argument("--model_path", help="Model path", default='weights/model')
    parser.add_argument("--n_classes", help="number of classes to classify", default=6)
    parser.add_argument("--batch_size", help="batch size", default=8)
    parser.add_argument("--epochs", help="number of epochs to train", default=500)
    parser.add_argument("--width", help="number of epochs to train", default=352)
    parser.add_argument("--height", help="number of epochs to train", default=224)
    parser.add_argument("--lr", help="init learning rate", default=1e-4)
    parser.add_argument("--n_gpu", help="number of the gpu", default=0)
    parser.add_argument("--r_samples", help="ratio of training samples used", default=1)
    args = parser.parse_args()

    n_gpu = int(args.n_gpu)
    os.environ["CUDA_VISIBLE_DEVICES"] = str(n_gpu)

    n_classes = int(args.n_classes)
    batch_size = int(args.batch_size)
    epochs = int(args.epochs)
    width =  int(args.width)
    height =  int(args.height)
    lr = float(args.lr)
    r_samples = float(args.r_samples)

    channels = 6 # input of 6 channels
    channels_image = 0
    channels_events = channels - channels_image
    folder_best_model = args.model_path
    name_best_model = os.path.join(folder_best_model,'best')
    dataset_path = args.dataset
    loader = Loader.Loader(dataFolderPath=dataset_path, n_classes=n_classes, problemType='segmentation',
                           width=width, height=height, channels=channels_image, channels_events=channels_events,
                           r_train_samples=r_samples)

    if not os.path.exists(folder_best_model):
        os.makedirs(folder_best_model)

    # build model and optimizer
    model = Segception.Segception_small(num_classes=n_classes, weights=None, input_shape=(None, None, channels))
    # model = Segception.Segception(num_classes=n_classes, weights=None, input_shape=(None, None, channels))

    # optimizer
    learning_rate = tf.Variable(lr)
    optimizer = tf.compat.v1.train.AdamOptimizer(learning_rate)

    # Init models (optional, just for get_params function)
    init_model(model, input_shape=(batch_size, width, height, channels))

    # Init saver. can use also ckpt = tfe.Checkpoint((model=model, optimizer=optimizer,learning_rate=learning_rate, global_step=global_step)
    variables_to_save = model.variables
    saver_model = tf.compat.v1.train.Saver(var_list=variables_to_save)
    variables_to_restore = model.variables #[x for x in model.variables if 'block1_conv1' not in x.name]
    restore_model = tf.compat.v1.train.Saver(var_list=variables_to_restore)

    # # restore if model saved and show number of params
    restore_state(restore_model, name_best_model)
    get_params(model)

    variables_to_optimize = model.variables

    if epochs > 0:
        train(loader=loader, model=model, epochs=epochs, batch_size=batch_size, augmenter='segmentation', lr=learning_rate,
            init_lr=lr, saver=saver_model, variables_to_optimize=variables_to_optimize, name_best_model=name_best_model,
            evaluation=True, preprocess_mode=None, n_test_samples_max=250)

    # Test best model
    print('Testing model')
    loader.suffle_segmentation()
    test_acc, test_miou = get_metrics(loader, model, loader.n_classes, train=True, flip_inference=True, scales=[0.75, 1, 1.5],
                                      write_images=True, preprocess_mode=None, n_samples_max=5)
    print('Test accuracy: ' + str(test_acc.numpy()))
    print('Test miou: ' + str(test_miou))
