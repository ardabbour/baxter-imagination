#!/usr/bin/env python
"""
    EASY BAXTER
    https://github.com/ardabbour/easy-baxter/

    Abdul Rahman Dabbour
    Cognitive Robotics Laboratory
    Faculty of Engineering and Natural Sciences
    Sabanci University

    An easier baxter interface.
"""

import sys
import time

import cv2
import numpy as np

import rospy
import tf
import moveit_commander
from cv_bridge import CvBridge
from sensor_msgs.msg import Image

import baxter_interface as b
import baxter_external_devices
from baxter_core_msgs.srv import SolvePositionIK, SolvePositionIKRequest


def enable_robot():
    """Enables Baxter. Please untuck arms before this!"""

    b.RobotEnable().enable()


def get_char(timeout=0.01):
    """Gets the character typed in the terminal. Useful for keyboard control."""

    return baxter_external_devices.getch(timeout)


def display_image(image_path):
    """Show the image located at the path on the display of Baxter."""

    img = cv2.imread(image_path)
    bridge = CvBridge()
    msg = bridge.cv2_to_imgmsg(img, encoding="bgr8")
    pub = rospy.Publisher("/robot/xdisplay", Image, latch=True, queue_size=1)
    pub.publish(msg)

    # Sleep to allow for image to be published.
    rospy.sleep(1)


class Camera(b.CameraController):
    """Class to do basic functions with the camera. To initialize, need to
    specify camera: `left_hand_camera`, `right_hand_camera`, `head_camera`."""

    def __init__(self, camera):
        all_cameras = ['left_hand_camera', 'right_hand_camera', 'head_camera']
        self.camera = camera
        all_cameras.remove(self.camera)
        self.other_cameras = all_cameras
        # self.close_other_cameras()
        self.publisher = '/cameras/' + self.camera + '/image'
        b.CameraController.__init__(self, camera)

    def close_other_cameras(self):
        """Closes other cameras to accomodate for the bandwith limitation."""
        for camera in self.other_cameras:
            print camera
            try:
                b.CameraController(camera).close()
            except AttributeError:
                rospy.INFO("Tried to close {} and failed".format(camera))

    def set_resolution(self, resolution):
        """Changes the resolution of the camera. For a list of valid resolution
        settings, refer to http://sdk.rethinkrobotics.com/wiki/Cameras."""

        self.resolution = resolution
        self.open()

    def set_fps(self, fps):
        """Changes the FPS of the camera. For a list of valid FPS settings,
        refer to http://sdk.rethinkrobotics.com/wiki/Cameras."""

        self.fps = fps
        self.open()


class Arm(b.Limb):
    """Class to control and do basic functions of a Baxter arm."""

    def __init__(self, limb):
        b.Limb.__init__(self, limb)
        grip = b.Gripper(limb)
        self.limb = limb
        self.grip = grip
        self.grip.calibrate()
        self.grip.open()
        self.grip.set_moving_force(100)
        self.grip.set_holding_force(100)
        self.robot = moveit_commander.RobotCommander()
        self.planning_group = moveit_commander.MoveGroupCommander(
            "{}_arm".format(limb))

    def get_pose(self, representation="euler"):
        """Acquires the pose of the endpoint of the limb and returns it as a
        list in the format, [x, y, z, roll, pitch, yaw]."""

        pose = self.endpoint_pose()
        position = list(pose["position"])
        if representation == "euler":
            orientation = list(
                tf.transformations.euler_from_quaternion(pose["orientation"]))
        elif representation == "quaternion":
            orientation = list(pose["orientation"])
        else:
            sys.exit("ERROR: Unknown representation queried.")
        return position + orientation

    def move_by_increment(self, dimension, increment):
        """Move the limb in the dimension incrementally. For example,
        move(x, 0.1) will move the limb in the positive x dimension by 0.1 m."""

        pose = self.get_pose()
        if dimension == "x":
            pose[0] += increment
        elif dimension == "y":
            pose[1] += increment
        elif dimension == "z":
            pose[2] += increment
        elif dimension == "roll":
            pose[3] += increment
        elif dimension == "pitch":
            pose[4] += increment
        elif dimension == "yaw":
            pose[5] += increment
        else:
            print "Warning: move by increment failed! Direction unidentified!"
        joint_positions = self.inverse_kinematics(pose)
        self.move_to_joint_positions(joint_positions)

    def move_to_pose(self, pose):
        """Move the limb to the pose using inverse kinematics."""

        joint_positions = self.inverse_kinematics(pose)
        self.move_to_joint_positions(joint_positions)

    def inverse_kinematics(self, pose):
        """Determine the joint angles that provide a desired pose for the
        robot"s end-effector."""

        quaternion_pose = moveit_commander.conversions.list_to_pose_stamped(
            pose, "base")

        node = "ExternalTools/" + self.name + "/PositionKinematicsNode/IKService"
        ik_service = rospy.ServiceProxy(node, SolvePositionIK)
        ik_request = SolvePositionIKRequest()

        ik_request.pose_stamp.append(quaternion_pose)

        try:
            rospy.wait_for_service(node, 5.0)
            ik_response = ik_service(ik_request)
        except (rospy.ServiceException, rospy.ROSException), error_message:
            rospy.logerr("Service request failed: {}".format(error_message,))
            sys.exit("ERROR: Failed to append pose.")

        if ik_response.isValid[0]:
            # convert response to joint position control dictionary
            limb_joints = dict(
                zip(ik_response.joints[0].name, ik_response.joints[0].position))
            return limb_joints
        else:
            rospy.logerr("{}".format(pose))
            sys.exit("ERROR: No valid joint configuration found. {}".format(pose))

    def pick_and_place(self, pick_pose, place_pose, height=0.15):
        """Simple pick and place manually, using overhand grasps."""

        above_pick = [pick_pose[0], pick_pose[1],
                      height, np.pi, 0.0, pick_pose[-1]]
        above_place = [place_pose[0], place_pose[1],
                       height, np.pi, 0.0, place_pose[-1]]

        self.move_to_pose(above_pick)
        self.move_to_pose(pick_pose)
        self.grip.close()
        time.sleep(2)
        self.move_to_pose(above_pick)
        self.move_to_pose(above_place)
        self.move_to_pose(place_pose)
        self.grip.open()
        time.sleep(2)
        self.move_to_pose(above_place)

    def pick_and_place_plan(self, pick_pose, place_pose, scene):
        """
        Generate a motion plan and execute it for pick and place using poses.

        """

        self.grip.open()
        time.sleep(2)

        def plan_to_pose(pose):
            target_pose = moveit_commander.conversions.list_to_pose_stamped(
                pick_pose, "world")

            self.planning_group.set_pose_target(
                target_pose, end_effector_link='{}_gripper'.format(self.limb))

            plan = self.planning_group.plan()

            return plan

        pick_plan = plan_to_pose(pick_pose)

        if not pick_plan.joint_trajectory.points:
            print "[ERROR] No pick trajectory found"
        else:
            self.planning_group.go(wait=True)

        self.grip.close()
        time.sleep(2)

        place_plan = plan_to_pose(place_pose)

        if not pick_plan.joint_trajectory.points:
            print "[ERROR] No place trajectory found"
        else:
            self.planning_group.go(wait=True)

        self.grip.open()
        time.sleep(2)
