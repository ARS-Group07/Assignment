#!/usr/bin/env python2.7
#
import rospy
from robot import Robot
import sequencer
import messagehelper
import matplotlib.pyplot as plt

from areaofinterest import AreaOfInterestFinder
from grids import Grid, GridVisualiser
from nav_msgs.msg import Odometry, OccupancyGrid, MapMetaData
from sensor_msgs.msg import CameraInfo, LaserScan
from matplotlib.animation import FuncAnimation

if __name__ == '__main__':
    try:
        rospy.init_node('assignment_node', anonymous=True)

        # wait for all important messages to arrive from various nodes
        occupancy_map = rospy.wait_for_message('/map', OccupancyGrid, timeout=5).data
        map_metadata = rospy.wait_for_message('/map_metadata', MapMetaData, timeout=5)
        camera_metadata = rospy.wait_for_message('camera/rgb/camera_info', CameraInfo, timeout=5)
        laser_range_max = rospy.wait_for_message('scan', LaserScan, timeout=5).range_max

        # ========== SETTINGS ==========
        grid_resolution = 0.2
        laser_density = 4  # eg sample a laser beam every 4 degrees
        fov = messagehelper.get_fov(camera_metadata)  # the field of view of the camera
        rospy.loginfo('fov: ' + str(fov))
        laser_angles = list(range(-int(fov / 2.), 0, laser_density)) + list(range(0, int(fov / 2.), laser_density))

        # ========== grid and visualiser initialisation ==========
        map_arr = messagehelper.create_map_array(occupancy_map, map_metadata, grid_resolution)
        grid = Grid(map_arr=map_arr)
        grid_vis = GridVisualiser(grid)
        # Instantiate and show the AOI Finder
        aoif = AreaOfInterestFinder(grid)

        the_robot = Robot(grid=grid, aoif=aoif,
                          laser_density = laser_density, laser_angles = laser_angles,laser_range_max=laser_range_max)

        # Show the grid visualiser
        plt.show(block=False)
        animate = FuncAnimation(grid_vis.fig, grid_vis.plot_grid, init_func=grid_vis.setup_frame)

        the_robot.sequencer = sequencer.Sequencer()
        the_robot.sequencer.sequence(the_robot)
        
    except rospy.ROSInterruptException:
        rospy.loginfo('ROSInterruptException encountered at %s' % rospy.get_time())
