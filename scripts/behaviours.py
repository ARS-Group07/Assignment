import rospy

from geometry_msgs.msg import Twist

from behaviours import *
from sequencer import *
from pose import Pose
from areaofinterest import AreaOfInterestFinder

class Behaviour:
    def __init__(self, name):
        self.name = name

    def act(self, robot, sequencer):
        print("Error: child class should override this")

    def warn_idle(self):
        i = 1

class Exploration(Behaviour):
    def __init__(self):
        Behaviour.__init__(self, "Exploration")
        self.last_goal_x = 0
        self.last_goal_y = 0
        self.idle_resend = False

    def act(self, robot, sequencer):
        aoif = robot.aoif

        if (not aoif.closest_area == -1):
            send = False
            if self.idle_resend:
                send = True
            elif not aoif.closest_cx == self.last_goal_x and not aoif.closest_cy == self.last_goal_y:
                send = True

            if send:
                self.idle_resend = False
                self.last_goal_x = aoif.closest_cx
                self.last_goal_y = aoif.closest_cy

                # TODO: Convert gx, gy to px, py
                wx, wy = robot.grid.to_world(aoif.closest_cx / aoif.scale,
                                             aoif.closest_cy / aoif.scale)
                robot.send_nav_goal(wx, wy)
                rospy.loginfo("Sending goal")

    def warn_idle(self):
        rospy.loginfo("Warning: robot is idle while it is supposed to be exploring")
        self.idle_resend = True


class Homing(Behaviour):
    # Static variable
    velocity_publisher = rospy.Publisher('/cmd_vel', Twist, queue_size=10)

    def __init__(self, sequencer):
        Behaviour.__init__(self, "Homing")

        self.sequencer = sequencer
        self.current_object_type = -1
        self.ang_vel = 0

    def act(self, robot, sequencer):
        if robot.last_laser_msg == None:
            return

        # First check if we're sufficiently close to an object, in which case we'll either ignore homing /
        laser_distances = [robot.last_laser_msg.ranges[-3:] + robot.last_laser_msg.ranges[0:3]]
        min_dist = min(laser_distances)

        twist = Twist()
        if min_dist < 0.25:
            twist.linear.x = 0.1
            twist.angular.z = self.ang_vel
        else:
            twist.linear.x = 0.
            twist.angular.z = 0.
            robot.set_object_found(self.current_object_type)
            self.sequencer.finished_homing()

        Homing.velocity_publisher.publish(twist)
