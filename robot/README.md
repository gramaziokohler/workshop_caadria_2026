Things I had to do to make it work on Parallels:

RobotStudio -> Controler -> RAPID -> T_CTRL -> RRC_Config_Ctrl
```
        b_RRC_AutoIPAddress:=FALSE;
        st_RRC_IP_AddressMan:="0.0.0.0";
```
So that RobotStudio is exposed to the ROS running on macOS

Then, in the `docker-compose.yml` the abb-driver needs:
```
- robot_ip:=10.211.55.3 # (the IP address of the VM Parallels)
```