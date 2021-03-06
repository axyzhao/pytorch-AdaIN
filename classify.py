import argparse
import torchvision.models as models
import datetime
import matplotlib.pyplot as plt
from torch import optim
import numpy as np
import resnet
from torchvision import datasets, transforms
from pathlib import Path

import torch
import glob
import torch.nn as nn
from PIL import Image
from torchvision import transforms
from torchvision.utils import save_image
import h5py

import net
from function import adaptive_instance_normalization, coral

train_files = glob.glob('data/PACS/*train.hdf5')
test_files = glob.glob('data/PACS/*test.hdf5')
target_domain = 'data/PACS/cartoon_train.hdf5'


# separate batch functions for image and labels, since we need to apply a transformation to images
def batch_img(iterable, batch_size=32):
    iterable = list(iterable)
    l = len(iterable)
    for i in range(0, l, batch_size):
        yield torch.stack([content_tf(elem) for elem in iterable[i:min(i+batch_size, l)]])

def batch(iterable, batch_size=32):
    iterable = list(iterable)
    l = len(iterable)
    for i in range(0, l, batch_size):
        yield iterable[i:min(i+batch_size, l)]

def open_file(filename):
    with h5py.File(filename, 'r') as f:
        # Get the data
        data = np.array(f['images'])
        labels = np.array(f['labels'])
    return data, labels

def content_tf(img):
    img = img.astype('float')
    img = Image.fromarray(img.astype('uint8'), 'RGB')
    transform_list = transforms.Compose([
        transforms.ToTensor(),
         #transforms.RandomCrop(256),
        # transforms.RandomHorizontalFlip(),
        #transforms.Normalize((0.5, 0.5, 0.5), (0.5, 0.5, 0.5))
    ])
    return transform_list(img).float()

def save_img(img, name):
    img = transforms.ToTensor()(img)
    plt.imsave(name, img.permute(1, 2, 0).numpy().astype('float')/255)

def shuffle_data(training_data, training_labels):
    idx = np.arange(len(training_data))
    np.random.shuffle(idx)
    training_data_shuffled = training_data[idx]
    training_labels_shuffled = training_labels[idx]
    return training_data_shuffled, training_labels_shuffled

def style_transfer(vgg, decoder, content, style, alpha=1.0,
                   interpolation_weights=None):
    assert (0.0 <= alpha <= 1.0)
    content_f = vgg(content)
    style_f = vgg(style)
    if interpolation_weights:
        _, C, H, W = content_f.size()
        feat = torch.FloatTensor(1, C, H, W).zero_().to(device)
        base_feat = adaptive_instance_normalization(content_f, style_f)
        for i, w in enumerate(interpolation_weights):
            feat = feat + w * base_feat[i:i + 1]
        content_f = content_f[0:1]
    else:
        feat = adaptive_instance_normalization(content_f, style_f)
    feat = feat * alpha + content_f * (1 - alpha)
    return decoder(feat)

def train(model, content_data, content_labels, style_data, style_labels, batch_size=32):
    all_count = correct_count = 0
    l = min(len(content_data), len(style_data))
    content_img_batches, content_label_batches = (batch_img(content_data, batch_size=batch_size),
                                            batch(style_labels, batch_size=batch_size))
    style_img_batches, style_label_batches = (batch_img(style_data, batch_size=batch_size),
                                            batch(style_labels, batch_size=batch_size))
    for i in range(l // batch_size):
        content_img, content_label = (next(content_img_batches), next(content_label_batches))
        style_img, style_label = (next(style_img_batches), next(style_label_batches))
        content_label = torch.tensor(content_label).long()
        style_label = torch.tensor(style_label).long()

        model.optimizer.zero_grad()
       # if np.random.binomial(1, 0.5):
       #     output = style_transfer(vgg, decoder, content_img_tf, style_img_tf,
        #                            args.alpha)
        #else:
         #   output = content_img_tf

        output = style_transfer(vgg, decoder, content_img, style_img, args.alpha)

        probabilities = model.forward(output)#.squeeze()
        loss = model.loss(probabilities, content_label)
        loss.backward()
        model.optimizer.step()
        if all_count % show_every == 0:
            print("Time: {}".format(datetime.datetime.now()))
            print("Loss at step {} is {}".format(i, loss))
            output_name = output_dir / 'output_{:s}{:s}'.format(str(i), '.png')
            style_name = output_dir / 'style_{:s}{:s}'.format(str(i), '.png')
            content_name = output_dir / 'content_{:s}{:s}'.format(str(i), '.png')
            save_image(output/255, str(output_name))
            save_image(content_img, str(content_name))
            save_image(style_img, str(style_name))
            
        for j in range(len(content_label)):
            true_label = content_label.numpy()[j]
            pred_label = probabilities[j].argmax()
            if(true_label == pred_label):
                correct_count += 1
            all_count += 1

    print("Number tested: {}".format(all_count))
    print("Model accuracy: {}".format(correct_count / all_count))

def evaluate(model, data, labels):
    print("\n")
    print("Evaluating model on target domain...")
    all_count = correct_count = 0
    for img, label in zip(data, labels):
        model.eval()
        with torch.no_grad():
            # create minibatch by unsqueezing
            img = content_tf(img).unsqueeze(0).float()
            label = torch.tensor(label).unsqueeze(0).long()
            # forward image through model
            probabilities = model.forward(img)
            loss_ = model.loss(probabilities, label)
            if all_count % show_every == 0:
                print("Time: {}".format(datetime.datetime.now()))
                print("Loss at step {} is {}".format(all_count, loss_))
            highest = probabilities.argmax(dim=1)
            for i in range(len(label)):
                true_label = label.numpy()[i]
                pred_label = probabilities[i].argmax()
                if(true_label == pred_label):
                    correct_count += 1
                all_count += 1
    print('\n')
    print("Number Of Images Tested =", all_count)
    print("\nModel Accuracy =", (correct_count/all_count))
parser = argparse.ArgumentParser()
# Basic options
parser.add_argument('--content', type=str,
                    help='File path to the content image')
parser.add_argument('--experiment_name', type=str,
                    help='The name of our experiment, for saving the model', default='experiment')
parser.add_argument('--content_dir', type=str,
                    help='Directory path to a batch of content images')
parser.add_argument('--style', type=str,
                    help='File path to the style image, or multiple style \
                    images separated by commas if you want to do style \
                    interpolation or spatial control')
parser.add_argument('--style_dir', type=str,
                    help='Directory path to a batch of style images')
parser.add_argument('--vgg', type=str, default='models/vgg_normalised.pth')
parser.add_argument('--decoder', type=str, default='models/decoder.pth')

# Additional options
parser.add_argument('--content_size', type=int, default=512,
                    help='New (minimum) size for the content image, \
                    keeping the original size if set to 0')
parser.add_argument('--style_size', type=int, default=512,
                    help='New (minimum) size for the style image, \
                    keeping the original size if set to 0')
parser.add_argument('--crop', action='store_true',
                    help='do center crop to create squared image')
parser.add_argument('--save_ext', default='.jpg',
                    help='The extension name of the output image')
parser.add_argument('--output', type=str, default='output',
                    help='Directory to save the output image(s)')

# Advanced options
parser.add_argument('--preserve_color', action='store_true',
                    help='If specified, preserve color of the content image')
parser.add_argument('--alpha', type=float, default=1.0,
                    help='The weight that controls the degree of \
                             stylization. Should be between 0 and 1')
parser.add_argument(
    '--style_interpolation_weights', type=str, default='',
    help='The weight for blending the style of multiple style images')
parser.add_argument(
    '--batch_size', type=int, default=1,
    help='batch size')
parser.add_argument(
    '--num_epochs', type=int, default=5,
    help='number of epochs to train')

args = parser.parse_args()
do_interpolation = False
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
output_dir = Path(args.output)
output_dir.mkdir(exist_ok=True, parents=True)
decoder = net.decoder
vgg = net.vgg
decoder.eval()
vgg.eval()
decoder.load_state_dict(torch.load(args.decoder))
vgg.load_state_dict(torch.load(args.vgg))
vgg = nn.Sequential(*list(vgg.children())[:31])

vgg.to(device)
decoder.to(device)
random_seed = 39

# model = resnet.resnet18()
num_output_classes = 8
model = torch.hub.load('pytorch/vision:v0.5.0', 'resnet18', pretrained=False)
num_ftrs = model.fc.in_features

model.fc = nn.Linear(num_ftrs, num_output_classes)
model.optimizer = optim.SGD(model.parameters(), lr=0.001, momentum=0.9, weight_decay=3e-4)
# batch size = 32
# random crop -- shift data to a different position
model.loss = nn.CrossEntropyLoss()
show_every = 100

style_data, style_labels = open_file(target_domain)
for f in train_files:
    if f == target_domain:
        continue
    content_data, content_labels = open_file(f)
    print("Starting training on new domains...")
    print("Transferring from {} --> {}".format(target_domain, f))

    for epoch in range(args.num_epochs):
        print("Starting epoch {}".format(epoch))
        # shuffle data
        content_data, content_labels = shuffle_data(content_data, content_labels)
        style_data, style_Labels = shuffle_data(style_data, style_labels)
        train(model, content_data, content_labels, style_data, style_labels, batch_size=args.batch_size)

evaluate(model, style_data, style_labels)
torch.save(model, '{}_resnet_classifier.pt'.format(args.experiment_name))
