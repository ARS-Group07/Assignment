from pose import Pose
import math
import rospy

from nav_msgs.msg import Odometry
from geometry_msgs.msg import PoseWithCovarianceStamped
from sensor_msgs.msg import LaserScan
from tf.transformations import euler_from_quaternion
from move_base_msgs.msg import MoveBaseAction, MoveBaseGoal

# Imports for faked object detection
import cv2, cv_bridge
import numpy as np
from sensor_msgs.msg import Image
from std_msgs.msg import String


class Robot:
    def __init__(self, grid, grid_resolution, grid_vis, aoif, laser_angles, laser_range_max, nav_client, map_arr,
                 x=0., y=0., yaw=0., sequencer=None, use_amcl_localisation=True):
        self.grid = grid
        self.grid_resolution = grid_resolution
        self.grid_vis = grid_vis
        self.aoif = aoif
        self.laser_angles = laser_angles
        self.laser_range_max = laser_range_max
        self.nav_client = nav_client
        self.pose = Pose(x, y, yaw)
        self.sequencer = sequencer
        self.map_arr = map_arr

        # ========== HOMING & OBJECT DETECTION ==========
        # Mappings:
        # 0 - Green cuboid
        # 1 - Red fire hydrant
        # 2 - Blue mailbox
        # 3 - White, numbered (5) cube
        self.objects_found = {0: False, 1: False, 2: False, 3: False}

        self.last_laser_msg = None
        self.homing_vel = 0

        if use_amcl_localisation:
            rospy.Subscriber('amcl_pose', PoseWithCovarianceStamped, self.get_amcl_data)
        else:
            rospy.Subscriber('odom', Odometry, self.get_odom_data)
        rospy.Subscriber('scan', LaserScan, self.get_laser_data)

        # Create the fake object detection
        # self.fake_object_detection = FakeObjectDetection(self)

    def get_amcl_data(self, msg):
        """ Gets predicted position data from the adaptive Monte Carlo module and uses it for the grids, etc. """
        quarternion = [msg.pose.pose.orientation.x, msg.pose.pose.orientation.y,
                       msg.pose.pose.orientation.z, msg.pose.pose.orientation.w]
        (_, _, yaw) = euler_from_quaternion(quarternion)
        px = msg.pose.pose.position.x
        py = msg.pose.pose.position.y

        self.pose.update_pose(px, py, yaw)
        self.grid.update_grid(px, py, flag='CURR')
        self.grid_vis.update_plot()
        if self.grid.is_fully_explored():
            rospy.loginfo('Map fully explored, resetting ...')
            self.grid.reset_grid(self.map_arr)

    def get_odom_data(self, msg):
        """ Gets predicted position data from the adaptive Monte Carlo module and uses it for the grids, etc. """
        quarternion = [msg.pose.pose.orientation.x, msg.pose.pose.orientation.y,
                       msg.pose.pose.orientation.z, msg.pose.pose.orientation.w]
        (_, _, yaw) = euler_from_quaternion(quarternion)
        px = msg.pose.pose.position.x
        py = msg.pose.pose.position.y

        self.pose.update_pose(px, py, yaw)
        self.grid.update_grid(px, py, flag='CURR')
        self.grid_vis.update_plot()

    def get_laser_data(self, msg):
        self.last_laser_msg = msg

        laser_distances = [msg.ranges[i] for i in self.laser_angles]
        for angle, dist in zip(self.laser_angles, laser_distances):
            if math.isinf(dist):  # if laser reads inf distance, clip to the laser's actual max range
                dist = self.laser_range_max

            plot_points = self.pose.plot_points_from_laser(angle, dist,
                                                           self.grid_resolution)  # convert to a list of scanned points
            for plot_point in plot_points:
                self.grid.update_grid(plot_point[0], plot_point[1], flag='NO_OBJ')  # update the grid at each point

        # build contours here, update best contour cx, cy
        self.aoif.get_grid_contours(self.pose.px, self.pose.py)

    def is_object_found(self, object_type):
        return self.objects_found.get(object_type)

    def set_object_found(self, object_type):
        if not self.is_object_found(object_type):
            print("FINALLY FOUND OBJECT " + str(object_type))
            while True:
                i = 1

        self.objects_found[object_type] = True

    def send_nav_goal(self, px, py):
        self.cancel_nav_goals()

        goal = MoveBaseGoal()
        goal.target_pose.header.frame_id = "map"
        goal.target_pose.header.stamp = rospy.Time.now()
        goal.target_pose.pose.position.x = px
        goal.target_pose.pose.position.y = py
        goal.target_pose.pose.orientation.w = 1.0
        self.nav_client.send_goal(goal)
        rospy.loginfo("Sent goal (" + str(goal.target_pose.pose.position.x) + ", " + str(
            goal.target_pose.pose.position.y) + "). Now waiting")
        wait = self.nav_client.wait_for_result(rospy.Duration(1))

    def cancel_nav_goals(self):
        self.nav_client.cancel_all_goals()


class FakeObjectDetection:
    def __init__(self, robot):
        self.robot = robot
        self.bridge = cv_bridge.CvBridge()
        self.downscale = 4  # How much to downscale the camera image by

        cv2.namedWindow('Green Object Detection', 1)
        rospy.Subscriber('camera/rgb/image_raw', Image, self.get_image_data)

    def get_image_data(self, msg):
        image = self.bridge.imgmsg_to_cv2(msg, desired_encoding='bgr8')
        (h, w) = image.shape[:2]
        image_resized = cv2.resize(image, (w / self.downscale, h / self.downscale))
        (h_resized, w_resized) = image_resized.shape[:2]
        hsv = cv2.cvtColor(image_resized, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, (36, 25, 25), (70, 255, 255))

        # Now detect contours
        _, contours, _ = cv2.findContours(mask, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
        closest_to_centre = 1e10
        for contour in contours:
            m = cv2.moments(contour)

            area = m['m00']
            if area > 30:  # The brick wall has small green contours that we want to ignore
                cx = int(m['m10'] / m['m00'])
                cy = int(m['m01'] / m['m00'])

                error = cx - w_resized / 2
                if error < closest_to_centre:
                    closest_to_centre = error

        if closest_to_centre != 1e10:
            # Apply proportional velocity of the following magnitude:
            homing_ang_vel = -float(closest_to_centre) / 100
            self.robot.sequencer.begin_homing(0, homing_ang_vel)

        # Show the mask
        cv2.imshow("Green Object Detection", mask)
        cv2.waitKey(3)
