import albumentations as A
import cv2
import numpy as np

from tfdet.core.bbox import random_bbox
    
def random_crop(x_true, y_true = None, bbox_true = None, mask_true = None, image_shape = None, min_area = 0., min_visibility = 0.):
    if image_shape is not None:
        result = albumentations(x_true, y_true, bbox_true, mask_true, min_area = min_area, min_visibility = min_visibility,
                                transform = [A.RandomCrop(*image_shape[:2], always_apply = True)])
    else:
        result = [v for v in [x_true, y_true, bbox_true, mask_true] if v is not None]
        result = result[0] if len(result) == 1 else tuple(result)
    return result

def mosaic(x_true, y_true = None, bbox_true = None, mask_true = None, image_shape = None, alpha = 0.2, pad_val = 0, min_area = 0., min_visibility = 0., e = 1e-12):
    """
    x_true = (4, H, W, C)
    y_true(without bbox_true) = (4, n_class)
    y_true(with bbox_true) = (4, P, 1 or n_class)
    bbox_true = (4, P, 4)
    mask_true(with bbox_true & instance mask_true) = (4, P, H, W, 1)
    mask_true(semantic mask_true) = (4, H, W, 1 or n_class)
    """
    h, w, c = np.shape(x_true[0]) if 2 < np.ndim(x_true[0]) else [*np.shape(x_true[0]), 1]
    if image_shape is not None:
        h, w, c = image_shape if 2 < len(image_shape) else [*image_shape, c]
    #else:
    #    h, w = h * 2, w * 2
    image = np.full([h, w, c], pad_val, dtype = x_true[0].dtype)
    center = [np.random.uniform(alpha, 1 - alpha), np.random.uniform(alpha, 1 - alpha)]
    center = np.random.uniform(np.multiply(center, -1), np.add([w, h], center)).astype(int)
    pad = []
    masks = None
    for i in range(4):
        if len(x_true) <= i:
            continue
        else:
            img = x_true[i] if 2 < np.ndim(x_true[i]) else np.expand_dims(x_true[i], axis = -1)
            img_h, img_w = np.shape(img)[:2]
            if i == 0:  # top left
                x1a, y1a, x2a, y2a = max(center[0] - img_w, 0), max(center[1] - img_h, 0), center[0], center[1]  # xmin, ymin, xmax, ymax (large image)
                x1b, y1b, x2b, y2b = img_w - (x2a - x1a), img_h - (y2a - y1a), img_w, img_h  # xmin, ymin, xmax, ymax (small image)
            elif i == 1:  # top right
                x1a, y1a, x2a, y2a = center[0], max(center[1] - img_h, 0), min(center[0] + img_w, w), center[1]
                x1b, y1b, x2b, y2b = 0, img_h - (y2a - y1a), min(img_w, x2a - x1a), img_h
            elif i == 2:  # bottom left
                x1a, y1a, x2a, y2a = max(center[0] - img_w, 0), center[1], center[0], min(h, center[1] + img_h)
                x1b, y1b, x2b, y2b = img_w - (x2a - x1a), 0, img_w, min(y2a - y1a, img_h)
            elif i == 3:  # bottom right
                x1a, y1a, x2a, y2a = center[0], center[1], min(center[0] + img_w, w), min(h, center[1] + img_h)
                x1b, y1b, x2b, y2b = 0, 0, min(img_w, x2a - x1a), min(y2a - y1a, img_h)
            image[y1a:y2a, x1a:x2a] = img[y1b:y2b, x1b:x2b]
            if mask_true is not None:
                if np.ndim(mask_true[i]) < 4: #semantic_mask
                    if i == 0:
                        masks = np.zeros([h, w, np.shape(mask_true[i])[-1]], dtype = mask_true[i].dtype)
                    masks[..., y1a:y2a, x1a:x2a, :] = mask_true[i][..., y1b:y2b, x1b:x2b, :]
                elif 3 < np.ndim(mask_true[i]): #instance_mask
                    mask = np.array(mask_true[i])
                    if i == 0:
                        masks = []
                    new_mask = np.zeros([len(mask), h, w, 1], dtype = mask.dtype)
                    new_mask[..., y1a:y2a, x1a:x2a, :] = mask[..., y1b:y2b, x1b:x2b, :]
                    if bbox_true is None:
                        new_mask = new_mask[0 < np.max(new_mask, axis = (-3, -2, -1))]
                    masks.append(new_mask)
            pad.append([x1a - x1b, y1a - y1b])
    
    if bbox_true is None and y_true is not None:
        h, w = image.shape[:2]
        area = [center[0] * center[1], (w - center[0]) * center[1], center[0] * (h - center[1]), (w - center[0]) * (h - center[1])][:min(4, len(x_true))]
        ratio = np.divide(area, sum(area))
        y_true = np.sum([np.multiply(l, r) for l, r in zip(y_true, ratio)], axis = 0)
    elif bbox_true is not None:
        scale_center, scale_pad = center, pad
        norm = False
        if not np.any(np.greater(bbox_true[:4], 1)):
            scale_center, scale_pad = np.divide(center, [w, h]), np.divide(pad, [w, h])
            h = w = 1
            norm = True
        bboxes = []
        labels = []
        for i, bbox in enumerate(bbox_true[:min(len(x_true), 4)]):
            bbox = np.divide(np.multiply(bbox, np.tile(np.shape(x_true[i])[:2][::-1], 2)), np.tile(np.shape(image)[:2][::-1], 2)) if norm else np.array(bbox)
            new_bbox = np.add(bbox, np.tile(scale_pad[i], 2))
            new_bbox = np.clip(new_bbox, 0, [w, h, w, h])
            
            area = (bbox[..., 2] - bbox[..., 0]) * (bbox[..., 3] - bbox[..., 1])
            new_area = (new_bbox[..., 2] - new_bbox[..., 0]) * (new_bbox[..., 3] - new_bbox[..., 1])
            flag = np.logical_and(min_area <= (new_area / (w * h + e)), min_visibility < (new_area / (area + e)))
            
            new_bbox = new_bbox[flag]
            bboxes.append(new_bbox)
            if y_true is not None:
                labels.append(np.array(y_true[i])[flag])
            if isinstance(masks, list):
                masks[i] = masks[i][flag]
        
        bbox_true = np.concatenate(bboxes, axis = 0) if 0 < len(bboxes) else np.zeros((0, 4), dtype = np.array(bbox_true).dtype)
        if y_true is not None:
            y_true = np.concatenate(labels, axis = 0) if 0 < len(labels) else np.zeros((0, np.shape(y_true)[-1]), dtype = np.array(y_true).dtype)
    if isinstance(masks, list):
        masks = np.concatenate(masks, axis = 0) if 0 < len(masks) else np.zeros((0, h, w, 1), dtype = np.array(mask_true).dtype)
    x_true, mask_true = image, masks
    result = [v for v in [x_true, y_true, bbox_true, mask_true] if v is not None]
    result = result[0] if len(result) == 1 else tuple(result)
    return result
    
def cut_mix(x_true, y_true = None, bbox_true = None, mask_true = None, alpha = 0.2, min_area = 0., min_visibility = 0., e = 1e-12):
    """
    x_true = (2, H, W, C)
    y_true(without bbox_true) = (2, n_class)
    y_true(with bbox_true) = (2, P, 1 or n_class)
    bbox_true = (2, P, 4)
    mask_true(with bbox_true & instance mask_true) = (2, P, H, W, 1)
    mask_true(semantic mask_true) = (2, H, W, 1 or n_class)
    """
    if len(x_true) == 1:
        x_true = x_true[0]
        y_true = y_true[0] if y_true is not None else None
        bbox_true = bbox_true[0] if bbox_true is not None else None
        mask_true = mask_true[0] if mask_true is not None else None
    else:
        r = np.random.beta(alpha, alpha)
        image = np.array(x_true[0])
        image_shape = image.shape[:2]
        crop_bbox = random_bbox(r, image_shape)
        image[crop_bbox[1]:crop_bbox[3], crop_bbox[0]:crop_bbox[2]] = x_true[1][crop_bbox[1]:crop_bbox[3], crop_bbox[0]:crop_bbox[2]]
        masks = None
        if mask_true is not None:
            if np.ndim(mask_true[0]) < 4:
                masks = np.array(mask_true[0])
                masks[..., crop_bbox[1]:crop_bbox[3], crop_bbox[0]:crop_bbox[2], :] = mask_true[1][..., crop_bbox[1]:crop_bbox[3], crop_bbox[0]:crop_bbox[2], :]
            elif 3 < np.ndim(mask_true[0]):
                masks = []
                for i in range(2):
                    if i == 0:
                        mask = np.array(mask_true[i])
                        mask[..., crop_bbox[1]:crop_bbox[3], crop_bbox[0]:crop_bbox[2], :] = 0
                    else:
                        m = np.array(mask_true[i])
                        mask = np.zeros([len(m), *image_shape, 1], dtype = m.dtype)
                        mask[..., crop_bbox[1]:crop_bbox[3], crop_bbox[0]:crop_bbox[2], :] = m[..., crop_bbox[1]:crop_bbox[3], crop_bbox[0]:crop_bbox[2], :]
                    if bbox_true is None:
                        mask = mask[0 < np.max(mask, axis = (-3, -2, -1))]
                    masks.append(mask)
        if bbox_true is None and y_true is not None:
            y_true = np.multiply(y_true[0], r) + np.multiply(y_true[1], 1 - r)
        elif bbox_true is not None:
            src_bbox, dst_bbox = np.array(bbox_true[0]), np.array(bbox_true[1])
            scale_crop_bbox = crop_bbox
            if not np.any(np.greater(np.concatenate([src_bbox, dst_bbox]), 1)):
                scale_crop_bbox = crop_bbox / np.tile(image_shape[:2][::-1], 2)
                image_shape = (1, 1)

            src_area = (src_bbox[..., 2] - src_bbox[..., 0]) * (src_bbox[..., 3] - src_bbox[..., 1])
            src_inter = np.maximum(np.minimum(src_bbox[..., 2], scale_crop_bbox[2]) - np.maximum(src_bbox[..., 0], scale_crop_bbox[0]), 0) * np.maximum(np.minimum(src_bbox[..., 3], scale_crop_bbox[3]) - np.maximum(src_bbox[..., 1], scale_crop_bbox[1]), 0)
            new_area = src_area - src_inter
            src_flag = np.logical_and(min_area <= (new_area / (image_shape[0] * image_shape[1] + e)), min_visibility < (new_area / (src_area + e)))

            dst_area = (dst_bbox[..., 2] - dst_bbox[..., 0]) * (dst_bbox[..., 3] - dst_bbox[..., 1])
            dst_bbox[..., [0, 2]] = np.clip(dst_bbox[..., [0, 2]], scale_crop_bbox[0], scale_crop_bbox[2])
            dst_bbox[..., [1, 3]] = np.clip(dst_bbox[..., [1, 3]], scale_crop_bbox[1], scale_crop_bbox[3])
            new_area = (dst_bbox[..., 2] - dst_bbox[..., 0]) * (dst_bbox[..., 3] - dst_bbox[..., 1])
            dst_flag = np.logical_and(min_area <= (new_area / (image_shape[0] * image_shape[1] + e)), min_visibility < (new_area / (dst_area + e)))

            bbox_true = np.concatenate([src_bbox[src_flag], dst_bbox[dst_flag]], axis = 0)
            if y_true is not None:
                y_true = np.concatenate([np.array(y_true[0])[src_flag], np.array(y_true[1])[dst_flag]], axis = 0)
            if isinstance(masks, list):
                masks[0], masks[1] = masks[0][src_flag], masks[1][dst_flag]
        if isinstance(masks, list):
            masks = np.concatenate(masks, axis = 0)
        x_true, mask_true = image, masks
    result = [v for v in [x_true, y_true, bbox_true, mask_true] if v is not None]
    result = result[0] if len(result) == 1 else tuple(result)
    return result

def albumentations(x_true, y_true = None, bbox_true = None, mask_true = None,
                   transform = [A.Blur(p = 0.01),
                                A.MedianBlur(p = 0.01),
                                A.ToGray(p = 0.01),
                                A.CLAHE(p = 0.01, clip_limit = 4., tile_grid_size = (8, 8)),
                                A.RandomBrightnessContrast(p = 0.01, brightness_limit = 0.2, contrast_limit = 0.2),
                                A.RGBShift(p = 0.01, r_shift_limit = 10, g_shift_limit = 10, b_shift_limit = 10),
                                A.HueSaturationValue(p = 0.01, hue_shift_limit = 10, sat_shift_limit = 40, val_shift_limit = 50),
                                A.ChannelShuffle(p = 0.01),
                                A.HorizontalFlip(p = 0.5),
                                #A.VerticalFlip(p = 0.5),
                                A.ShiftScaleRotate(p = 0.01, rotate_limit = 30, shift_limit = 0.0625, scale_limit = 0.1, interpolation = cv2.INTER_LINEAR, border_mode = cv2.BORDER_CONSTANT),
                                #A.RandomResizedCrop(p = 0.01, height = 512, width = 512, scale = [0.5, 1.]),
                                A.ImageCompression(p = 0.01, quality_lower = 75),
                               ],
                   min_area = 0., min_visibility = 0.):
    if 0 < len(transform):
        method = A.Compose(transform, bbox_params = {"format":"albumentations", "label_fields":["class_labels"], "min_area":min_area, "min_visibility":min_visibility})
        
        h, w = np.shape(x_true)[:2]
        class_labels = None
        if bbox_true is not None:
            bbox_true = np.array(bbox_true)
            indices = np.where(np.max(0 < bbox_true, axis = -1, keepdims = True) != 0)[0]
            bbox_true = bbox_true[indices]
            bbox_norm = not np.any(np.greater(bbox_true, 1))
            if not bbox_norm:
                bbox_true = np.divide(bbox_true, [w, h, w, h])
            area = (bbox_true[..., 3] - bbox_true[..., 1]) * (bbox_true[..., 2] - bbox_true[..., 0])
            indices2 = np.where(0 < area)[0]
            bbox_true = bbox_true[indices2]
            if y_true is not None:
                y_true = np.array(y_true)[indices[indices2]]
            class_labels = np.arange(len(bbox_true))
        if mask_true is not None and 3 < np.ndim(mask_true):
            if bbox_true is not None:
                mask_true = np.array(mask_true)[indices[indices2]]
            mask_true = [m for m in mask_true]
        
        args = {"image":x_true, "class_labels":class_labels if class_labels is not None else [0]}
        args["bboxes"] = bbox_true if bbox_true is not None else [[0, 0, 1, 1]]
        if mask_true is not None:
            args["masks" if 3 < np.ndim(mask_true) else "mask"] = mask_true
        
        aug_result = method(**args)
        indices = aug_result["class_labels"] if class_labels is not None else (np.arange(len(y_true)) if y_true is not None else [])
        x_true = aug_result["image"]
        ori_bbox_true = bbox_true
        if y_true is not None:
            y_true = np.array(y_true)[indices]
        if bbox_true is not None:
            new_bbox_true = aug_result["bboxes"]
            if len(new_bbox_true) == 0:
                bbox_true = np.zeros((0, 4), dtype = bbox_true.dtype)
            else:
                bbox_true = np.clip(new_bbox_true, 0, 1)
                bbox_true = bbox_true if bbox_norm else np.round(np.multiply(new_bbox_true, np.tile(np.shape(x_true)[:2][::-1], 2))).astype(int)
        if mask_true is not None:
            mask_true = np.array(aug_result["masks" if 3 < np.ndim(mask_true) else "mask"])
            if 3 < np.ndim(mask_true):
                if bbox_true is not None:
                    mask_true = mask_true[indices]
                else:
                    mask_true = mask_true[0 < np.max(mask_true, axis = (-3, -2, -1))]
        
    result = [v for v in [x_true, y_true, bbox_true, mask_true] if v is not None]
    result = result[0] if len(result) == 1 else tuple(result)
    return result