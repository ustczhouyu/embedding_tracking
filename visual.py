import cv2
import matplotlib.pyplot as plt
import numpy as np
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler
from postprocessing import embedding_to_instance

from utils import *


def principal_component_analysis(embedding_pred, embedding_dim):
    width, height, _ = embedding_pred.shape
    embedding_pred_flat = np.reshape(embedding_pred, (-1, embedding_dim))
    embedding_pred_flat = StandardScaler().fit_transform(embedding_pred_flat)
    pca = PCA(n_components=3)
    pc_flat = pca.fit_transform(embedding_pred_flat)
    pc = np.reshape(pc_flat, (width, height, 3))
    pc = normalize(pc)

    return pc


def flow_to_rgb(flow):
    # read nonzero optical flow
    image_size = flow.shape[0]
    direction_hsv = np.zeros((image_size, image_size, 3))
    dx = flow[:, :, 0]
    dy = flow[:, :, 1]
    # define min and max
    mag_max = np.sqrt(2)
    mag_min = 0
    angle_max = np.pi
    angle_min = -np.pi
    angles = np.arctan2(dx, dy)
    magnitudes = np.sqrt(np.power(dx, 2) + np.power(dy, 2))
    # convert to hsv
    hue = normalize(angles, [angle_min, angle_max])
    saturation = normalize(magnitudes, [mag_min, mag_max])
    value = np.zeros(angles.shape) + 1
    direction_hsv[:, :, 0] = hue
    direction_hsv[:, :, 1] = saturation
    direction_hsv[:, :, 2] = value
    direction_rgb = matplotlib.colors.hsv_to_rgb(direction_hsv)
    return direction_rgb


def imgs_to_video(images, video_name, fps):
    # assumes `images` contains square images in shape of (x, x, 3)
    height, width = images[0].shape[0:2]
    video = cv2.VideoWriter(video_name, 0, fps, (width, height))
    for image in images:
        video.write(image)
    video.release()
    return


def flows_to_video(flows, video_name, fps):
    # assumes `flows` contains square images in shape of (x, x, 2)
    images = []
    for flow in flows:
        image = flow_to_rgb(flow)
        image = image * 255
        image = image.astype(np.uint8)
        images.append(image)
    imgs_to_video(images, video_name, fps)
    return


def float_to_uint8(data):
    data = data * 255
    data = data.astype(np.uint8)
    return data


def pair_embedding_to_video(sequence, model, params, video_name, fps):
    class_num     = params.NUM_CLASSES
    embedding_dim = params.EMBEDDING_DIM
    image_size    = params.IMG_SIZE
    output_size   = params.OUTPUT_SIZE
    boards = []
    for i in range(len(sequence) - 1):
        image = sequence[i]['image']
        image_2 = sequence[i+1]['image']
        board = np.zeros((image_size * 2, image_size * 2, 3))
        x, _ = prep_double_frame(sequence[i+1], sequence[i], params)
        outputs = model.predict(x)
        outputs = np.squeeze(outputs)
        embedding_pred = outputs[:, :, (class_num*2):(class_num*2 + embedding_dim)]
        prev_embedding_pred = outputs[:, :, (class_num*2 + embedding_dim):((class_num*2 + embedding_dim*2))]
        combined_embedding_pred = np.zeros((output_size, output_size*2, embedding_dim))
        combined_embedding_pred[:, :output_size, :] = prev_embedding_pred
        combined_embedding_pred[:, output_size:, :] = embedding_pred
        board[:image_size, :image_size, :] = image_2
        board[:image_size, image_size:, :] = image
        pc = principal_component_analysis(combined_embedding_pred, embedding_dim)
        pc = resize_img(pc, image_size, image_size*2)
        board[image_size:, image_size:, :] = pc[:, image_size:, :]
        board[image_size:, :image_size, :] = pc[:, :image_size, :]
        board = float_to_uint8(board)
        boards.append(board)
    imgs_to_video(boards, video_name, fps)
    return


def colorize_instances(instance_masks):
    # show instance mask and predicted embeddings
    width, height = instance_masks.shape
    instances_color = np.zeros((width, height, 3))
    
    num_instances = int(np.max(instance_masks))
    random_colors = np.random.rand(num_instances, 3)

    for i in range(num_instances):
        instances_color[instance_masks == i] = random_colors[i, :]

    return instances_color


def colorize_class_mask(class_mask_int, class_num):
    class_max = class_num - 1
    width, height = class_mask_int.shape
    class_mask_int_color = np.zeros((width, height, 3))
    class_mask_int_color[:, :, 0] = class_mask_int/class_max
    class_mask_int_color[:, :, 1] = class_mask_int/class_max
    class_mask_int_color[:, :, 2] = class_mask_int/class_max

    return class_mask_int_color


def visualize(embedding_pred, embedding_dim, output_size, class_mask_int_pred,
              cluster_all_class, instance_mask_gt, class_num, class_mask_int_gt, image):
    # pca on embedding purely for visualization, not for clustering
    pc = principal_component_analysis(embedding_pred, embedding_dim)

    # prepare predicted embeddings (front/back)
    show_mask = np.expand_dims(class_mask_int_pred > 0, axis=-1)
    embedding_masked = np.multiply(pc, show_mask)

    instance_mask_pred_color = colorize_instances(cluster_all_class)
    instance_mask_gt_color   = colorize_instances(instance_mask_gt)

    class_mask_int_pred_color = colorize_class_mask(class_mask_int_pred, class_num)
    class_mask_int_gt_color   = colorize_class_mask(class_mask_int_gt, class_num)

    image = cv2.resize(image, (output_size, output_size))
    image = (image + 1)/2
    board = np.zeros((output_size, output_size*7, 3))
    board[:, (output_size*0):(output_size*1), :] = image
    board[:, (output_size*1):(output_size*2), :] = pc
    board[:, (output_size*2):(output_size*3), :] = embedding_masked
    board[:, (output_size*3):(output_size*4), :] = instance_mask_pred_color
    board[:, (output_size*4):(output_size*5), :] = instance_mask_gt_color
    board[:, (output_size*5):(output_size*6), :] = class_mask_int_pred_color
    board[:, (output_size*6):(output_size*7), :] = class_mask_int_gt_color

    plt.figure(figsize=(4 * 7, 4))
    plt.imshow(board)
    plt.show()


def single_eval(model, x, y, params):
    class_num                = params.NUM_CLASSES
    embedding_dim            = params.EMBEDDING_DIM
    output_size              = params.OUTPUT_SIZE

    outputs = model.predict(x)
    class_mask_pred = outputs[0, :, :, :class_num]
    embedding_pred  = outputs[0, :, :, class_num:(class_num + embedding_dim)]
    class_mask_int_pred = np.argmax(class_mask_pred, axis=-1)
    cluster_all_class = embedding_to_instance(embedding_pred, class_mask_pred, params)
    image = np.squeeze(x)
    class_mask_gt    = y[0, ..., 0]
    instance_mask_gt = y[0, ..., 1]
    visualize(embedding_pred, embedding_dim, output_size, class_mask_int_pred,
              cluster_all_class, instance_mask_gt, class_num, class_mask_gt, image)


def eval_pair(model, pair, params):
    class_num                = params.NUM_CLASSES
    embedding_dim            = params.EMBEDDING_DIM
    output_size              = params.OUTPUT_SIZE
    image_size               = params.IMG_SIZE

    images = np.zeros((image_size, image_size*2, 3))
    board = np.zeros((output_size*2, output_size*7, 3))
    prev_image_info, image_info = pair

    image                  = image_info['image']
    identity_mask_gt       = image_info['identity_mask']
    class_mask_gt_int      = image_info['class_mask']

    prev_image             = prev_image_info['image']
    prev_identity_mask_gt  = prev_image_info['identity_mask']
    prev_class_mask_gt_int = prev_image_info['class_mask']
    optical_flow_gt        = prev_image_info['optical_flow']

    images[:, :image_size, :] = prev_image
    images[:, image_size:, :] = image

    x, _ = prep_double_frame(image_info, prev_image_info, params)
    outputs = model.predict(x)
    outputs = np.squeeze(outputs)

    class_mask_pred      = outputs[:, :, :class_num]
    prev_class_mask_pred = outputs[:, :, class_num:(class_num*2)]
    embedding_pred       = outputs[:, :, (class_num*2):(class_num*2 + embedding_dim)]
    prev_embedding_pred  = outputs[:, :, (class_num*2 + embedding_dim):((class_num*2 + embedding_dim*2))]
    optical_flow_pred    = outputs[:, :, (class_num*2 + embedding_dim*2):]

    combined_class_mask_pred_int = np.zeros((output_size, output_size*2))
    combined_class_mask_gt_int   = np.zeros((output_size, output_size*2))
    combined_embedding_pred      = np.zeros((output_size, output_size*2, embedding_dim))

    # resize to output_size
    class_mask_gt_int      = resize_img(class_mask_gt_int,      output_size, output_size)
    prev_class_mask_gt_int = resize_img(prev_class_mask_gt_int, output_size, output_size)
    identity_mask_gt       = resize_img(identity_mask_gt,       output_size, output_size)
    prev_identity_mask_gt  = resize_img(prev_identity_mask_gt,  output_size, output_size)
    optical_flow_gt        = resize_img(optical_flow_gt,        output_size, output_size)

    # argmax
    class_mask_pred_int      = np.argmax(class_mask_pred, axis = -1)
    prev_class_mask_pred_int = np.argmax(prev_class_mask_pred, axis = -1)

    # fill in value to the combined visualization
    combined_class_mask_pred_int[:, :output_size]  = class_mask_pred_int
    combined_class_mask_pred_int[:, output_size:]  = prev_class_mask_pred_int
    combined_class_mask_gt_int[:, :output_size]    = class_mask_gt_int
    combined_class_mask_gt_int[:, output_size:]    = prev_class_mask_gt_int
    combined_embedding_pred[:, :output_size, :]    = embedding_pred
    combined_embedding_pred[:, output_size:, :]    = prev_embedding_pred

    cluster_all_class = embedding_to_instance(combined_embedding_pred, combined_class_mask_pred_int, params)

    # colorize for visualization
    combined_identity_mask_gt         = np.zeros((output_size, output_size*2))
    combined_identity_mask_gt[:, :output_size] = identity_mask_gt
    combined_identity_mask_gt[:, output_size:] = prev_identity_mask_gt
    combined_identity_mask_gt_color   = colorize_instances(combined_identity_mask_gt)
    identity_mask_gt_color            = combined_identity_mask_gt_color[:, :output_size, :]
    prev_identity_mask_gt_color       = combined_identity_mask_gt_color[:, output_size:, :]
    class_mask_gt_color               = colorize_class_mask(class_mask_gt_int, class_num)
    prev_class_mask_gt_color          = colorize_class_mask(prev_class_mask_gt_int, class_num)
    optical_flow_gt_color             = flow_to_rgb(optical_flow_gt)

    combined_identity_mask_pred_color = colorize_instances(cluster_all_class)
    identity_mask_pred_color          = combined_identity_mask_pred_color[:, :output_size]
    prev_identity_mask_pred_color     = combined_identity_mask_pred_color[:, output_size:]
    class_mask_pred_color             = colorize_class_mask(class_mask_pred_int, class_num)
    prev_class_mask_pred_color        = colorize_class_mask(prev_class_mask_pred_int, class_num)
    optical_flow_pred_color           = flow_to_rgb(optical_flow_pred)

    pc = principal_component_analysis(combined_embedding_pred, embedding_dim)
    show_mask = np.expand_dims(combined_class_mask_gt_int > 0, axis=-1)
    embedding_masked = np.multiply(pc, show_mask)
    embedding_pred_pc_masked      = embedding_masked[:, :output_size, :]
    prev_embedding_pred_pc_masked = embedding_masked[:, output_size:, :]
    embedding_pred_pc             = pc[:, :output_size, :]
    prev_embedding_pred_pc        = pc[:, output_size:, :]

    # fill the display board
    board[:output_size, :output_size]                    = prev_identity_mask_gt_color
    board[:output_size, output_size:(output_size*2)]     = prev_class_mask_gt_color
    board[:output_size, (output_size*2):(output_size*3)] = identity_mask_gt_color
    board[:output_size, (output_size*3):(output_size*4)] = class_mask_gt_color
    board[:output_size, (output_size*4):(output_size*5)] = optical_flow_gt_color
    
    board[output_size:, :output_size]                    = prev_identity_mask_pred_color
    board[output_size:, output_size:(output_size*2)]     = prev_class_mask_pred_color
    board[output_size:, (output_size*2):(output_size*3)] = identity_mask_pred_color
    board[output_size:, (output_size*3):(output_size*4)] = class_mask_pred_color
    board[output_size:, (output_size*4):(output_size*5)] = optical_flow_pred_color

    board[:output_size, (output_size*5):(output_size*6)] = prev_embedding_pred_pc_masked
    board[output_size:, (output_size*5):(output_size*6)] = prev_embedding_pred_pc
    board[:output_size, (output_size*6):(output_size*7)] = embedding_pred_pc_masked
    board[output_size:, (output_size*6):(output_size*7)] = embedding_pred_pc

    plt.figure(figsize=(2*2, 2*2))
    plt.imshow(images)

    plt.figure(figsize=(2*6, 2*2))
    plt.imshow(board)
    plt.show()
