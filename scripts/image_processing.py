#!/usr/bin/env python
"""
    EASY BAXTER
    https://github.com/ardabbour/easy-baxter/

    Abdul Rahman Dabbour
    Cognitive Robotics Laboratory
    Faculty of Engineering and Natural Sciences
    Sabanci University

    Processes an image to get the arrangement of objects on a table.
"""

from argparse import ArgumentParser
from itertools import repeat


import rospy
import roslib
import rospkg
from rospy.numpy_msg import numpy_msg
from cv_bridge import CvBridge
from sensor_msgs.msg import Image
from rospy_tutorials.msg import Floats

import cv2
import numpy as np

import easy_baxter as eb

PKG = 'easy_baxter'
roslib.load_manifest(PKG)
PKG_DIR = rospkg.RosPack().get_path(PKG)

# Actual ROI dimentions measured in cm; this changes depending on depth
ACTUAL_WIDTH = 43
ACTUAL_HEIGHT = 20

# HSV-based filtering ranges
LOWER_BLUE = np.array([90, 80, 10])
UPPER_BLUE = np.array([160, 255, 170])

LOWER_GREEN = np.array([80, 100, 0])
UPPER_GREEN = np.array([130, 255, 255])

LOWER_YELLOW = np.array([5, 60, 75])
UPPER_YELLOW = np.array([40, 130, 255])

# Some colors, like red, use an OR filter to capture the entire range
LOWER_RED_1 = np.array([0, 70, 0])
UPPER_RED_1 = np.array([10, 255, 255])
LOWER_RED_2 = np.array([150, 70, 50])
UPPER_RED_2 = np.array([179, 255, 255])

# Camera settings
FPS = 15
GAIN = 40
EXPOSURE = 80
RESOLUTION = (640, 400)
WHITE_BALANCE_RED = -1
WHITE_BALANCE_BLUE = -1
WHITE_BALANCE_GREEN = -1


def get_angle(rect_points):
    """Get the angle from the long edge to avoid confusion!"""

    edge1 = rect_points[1] - rect_points[0]
    edge2 = rect_points[2] - rect_points[1]

    used_edge = edge1
    if np.linalg.norm(edge2) > np.linalg.norm(edge1):
        used_edge = edge2

    reference = [1.0, 0.0]
    my_angle = np.arccos(np.linalg.norm(reference) /
                         np.linalg.norm(used_edge) /
                         reference[0]*used_edge[0] +
                         reference[1]*used_edge[1]) + np.pi

    return ((my_angle)) % (2 * np.pi) - np.pi


def detect(image, dimensions, scale, display):
    """Extracts the centroids and orientations of objects from the image."""

    image = cv2.cvtColor(image, cv2.COLOR_HSV2BGR_FULL)

    # Extract edges from resulting image
    canny = cv2.Canny(image, 10, 80)

    # Contouring
    detected = []
    contours, _ = cv2.findContours(
        canny, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for i in contours:
        if cv2.contourArea(i) > 800.0:
            rect = cv2.minAreaRect(i)
            box_points = np.intp(cv2.boxPoints(rect))
            moments = cv2.moments(box_points)

            # Centroid Calculation for x and y coordinates
            center_x = float(moments['m10']/moments['m00']) - dimensions[0]/2.0
            center_x = round(center_x * scale[0], 2)
            center_y = float(moments['m01']/moments['m00']) - dimensions[1]/2.0
            center_y = round(center_y * scale[1], 2)

            # Angle Calculation for theta coordinate
            angle = round(get_angle(box_points), 2)

            detected.append([[-center_x, center_y, 6.5], [0.0, 0.0, angle]])
            cv2.drawContours(display, [box_points], 0, (255, 255, 0), 2)

    return detected, display


def increase_contrast(image):
    """Uses CLAHE (Contrast Limited Adaptive Histogram Equalization) to increase
    the contrast of an image. Found on Stack Overflow, written by Jeru Luke."""

    # Converting image to LAB Color model
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)

    # Splitting the LAB image to different channels
    l, a, b = cv2.split(lab)

    # Applying CLAHE to L-channel---
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    cl = clahe.apply(l)

    # Merge the CLAHE enhanced L-channel with the a and b channel
    limg = cv2.merge((cl, a, b))

    # Converting image from LAB Color model to RGB model
    final = cv2.cvtColor(limg, cv2.COLOR_LAB2BGR)

    return final


def process_image(raw):
    """Processes the image."""

    # Define an initial region of interest (ROI) based on frame size
    height, width = raw.shape[:2]
    height = float(height)
    width = float(width)

    # Define the upper left corner of the area we are interested in.
    upper_left = (0, int(height/3))
    bottom_right = (int(width), int(height))

    horizontal = (upper_left[0], bottom_right[0])
    vertical = (upper_left[1], bottom_right[1])

    cropped_width = float(horizontal[1] - horizontal[0])
    cropped_height = float(vertical[1] - vertical[0])
    dimensions = [cropped_width, cropped_height]

    width_scale = ACTUAL_WIDTH/cropped_width
    height_scale = ACTUAL_HEIGHT/cropped_height
    scale = [width_scale, height_scale]

    # Crop image to ROI
    image = raw[vertical[0]:vertical[1], horizontal[0]:horizontal[1]]
    raw_cropped = image
    cv2.rectangle(raw, upper_left, bottom_right, (0, 0, 0), 2)

    # rotate the image by 180 degrees
    center = (width/2, height/2)
    rotation_matrix = cv2.getRotationMatrix2D(center, 180, 1.0)
    rotated_raw = cv2.warpAffine(
        raw, rotation_matrix, (int(width), int(height)))

    cv2.namedWindow('Original', cv2.WINDOW_NORMAL)
    cv2.imshow('Original', rotated_raw)
    cv2.waitKey(5)

    # Remove noise from image
    for _ in repeat(None, 4):
        image = cv2.medianBlur(image, 5)

    # Convert to HSV color space
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)

    # Create structuring element for morphological operations
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (11, 11))

    # Red thresholding
    mask_r_1 = cv2.inRange(hsv, LOWER_RED_1, UPPER_RED_1)
    mask_r_2 = cv2.inRange(hsv, LOWER_RED_2, UPPER_RED_2)
    mask_r = cv2.bitwise_or(mask_r_1, mask_r_2)
    mask_r = cv2.dilate(mask_r, kernel, iterations=2)
    mask_r = cv2.erode(mask_r, kernel, iterations=3)
    res_r = cv2.bitwise_and(image, image, mask=mask_r)

    # # Blue thresholding
    mask_b = cv2.inRange(hsv, LOWER_BLUE, UPPER_BLUE)
    mask_b = cv2.dilate(mask_b, kernel, iterations=2)
    mask_b = cv2.erode(mask_b, kernel, iterations=3)
    res_b = cv2.bitwise_and(image, image, mask=mask_b)

    # Green thresholding
    mask_g = cv2.inRange(hsv, LOWER_GREEN, UPPER_GREEN)
    mask_g = cv2.dilate(mask_g, kernel, iterations=2)
    mask_g = cv2.erode(mask_g, kernel, iterations=3)
    res_g = cv2.bitwise_and(image, image, mask=mask_g)

    # Yellow thresholding
    mask_y = cv2.inRange(hsv, LOWER_YELLOW, UPPER_YELLOW)
    mask_y = cv2.dilate(mask_y, kernel, iterations=2)
    mask_y = cv2.erode(mask_y, kernel, iterations=3)
    res_y = cv2.bitwise_and(image, image, mask=mask_y)

    cubes, display = detect(res_g, dimensions, scale, raw_cropped)
    cuboids, display = detect(res_y, dimensions, scale, display)
    long_cuboids, display = detect(res_r, dimensions, scale, display)

    cv2.namedWindow('Detection', cv2.WINDOW_NORMAL)
    # rotate the image by 180 degrees
    height, width = display.shape[:2]
    center = (width/2, height/2)
    rotation_matrix = cv2.getRotationMatrix2D(center, 180, 1.0)
    display = cv2.warpAffine(display, rotation_matrix,
                             (int(width), int(height)))
    cv2.imshow('Detection', display)
    cv2.waitKey(50)

    # Combine all thresholded images
    combined = res_r + res_b + res_y
    # combined = res_r + res_g + res_y

    return [cubes, cuboids, long_cuboids], combined


def init_camera(camera_name):
    """Initializes the camera."""

    camera = eb.Camera(camera_name)

    if FPS > -1:
        camera.fps = FPS
    if GAIN > -1:
        camera.gain = GAIN
    if EXPOSURE > -1:
        camera.exposure = EXPOSURE
    if RESOLUTION > -1:
        camera.resolution = RESOLUTION
    if WHITE_BALANCE_RED > -1:
        camera.white_balance_red = WHITE_BALANCE_RED
    if WHITE_BALANCE_BLUE > -1:
        camera.white_balance_blue = WHITE_BALANCE_BLUE
    if WHITE_BALANCE_GREEN > -1:
        camera.white_balance_green = WHITE_BALANCE_GREEN

    camera.open()

    # Camera needs time to adjust its white balance
    rospy.sleep(1)


def main(node, publisher, camera):
    """Creates image processing node and keeps it running."""

    rospy.init_node(node)

    # Smile!
    eb.display_image(PKG_DIR + '/smiley.jpg')

    # Create publisher
    pub_cubes = rospy.Publisher(
        publisher + '/cubes', numpy_msg(Floats), queue_size=10)
    pub_cylinders = rospy.Publisher(
        publisher + '/cylinders', numpy_msg(Floats), queue_size=10)
    pub_pluses = rospy.Publisher(
        publisher + '/pluses', numpy_msg(Floats), queue_size=10)
    pub_img = rospy.Publisher(
        '/cameras/' + camera + '/image/processed', Image, queue_size=1)

    # Initialize the camera
    init_camera(camera)

    # Initialize CV Bridge
    bridge = CvBridge()

    # Subscribe to the specified ROS topic and process it continuously
    while not rospy.is_shutdown():
        msg = rospy.wait_for_message('/cameras/' + camera + '/image', Image)
        raw = bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")

        arrangement, processed = process_image(raw)

        img_msg = bridge.cv2_to_imgmsg(processed, encoding="bgr8")
        cubes_msg = np.array(arrangement[0], dtype=np.float32).flatten()
        cylinders_msg = np.array(arrangement[1], dtype=np.float32).flatten()
        pluses_msg = np.array(arrangement[2], dtype=np.float32).flatten()

        pub_img.publish(img_msg)
        pub_cubes.publish(cubes_msg)
        pub_cylinders.publish(cylinders_msg)
        pub_pluses.publish(pluses_msg)


if __name__ == "__main__":
    PARSER = ArgumentParser()
    PARSER.add_argument("--publisher", "-p",
                        help="ROS topic to publish to",
                        default="/easy_baxter/arrangement",
                        type=str)
    PARSER.add_argument("--camera", "-c",
                        help="Camera name",
                        default="left_hand_camera",
                        type=str)
    PARSER.add_argument("--node_name", "-n",
                        help="Node name",
                        default="image_processing",
                        type=str)
    ARGS = PARSER.parse_args()

    main(ARGS.node_name, ARGS.publisher, ARGS.camera)
