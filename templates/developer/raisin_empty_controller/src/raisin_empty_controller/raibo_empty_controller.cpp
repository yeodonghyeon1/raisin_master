//
// Created by donghoon on 8/23/22.
// 
 
#include <filesystem>
#include "raisin_util/raisin_directories.hpp"

#include "raisin_empty_controller/raibo_empty_controller.hpp"

namespace raisin {

namespace controller {

using std::placeholders::_1;
using std::placeholders::_2;

raiboEmptyController::raiboEmptyController(
    raisim::World & world, raisim::RaisimServer & server,
    raisim::World & worldSim, raisim::RaisimServer & serverSim, GlobalResource & globalResource)
  : Controller("raibo_empty_controller", world, server, worldSim, serverSim, globalResource),
    param_(parameter::ParameterContainer::getRoot()["raibo_empty_controller"])
{
  param_.loadFromPackageParameterFile("raisin_empty_controller");
  controllerType_ = ControllerType::TEST;
}

bool raiboEmptyController::create() {
  n_joints_ = 12;

  clk_ = 0;
  one_sec_clk_ = static_cast<int>(param_("comm_rate"));
  double joint_p_gain = param_("joint_p_gain");
  double joint_d_gain = param_("joint_d_gain");

  p_gain_.setZero(robotHub_->getDOF());
  d_gain_.setZero(robotHub_->getDOF());
  p_target_.setZero(robotHub_->getGeneralizedCoordinateDim());
  d_target_.setZero(robotHub_->getDOF());
  p_target_.tail(12) = robotHub_->getGeneralizedCoordinate().e().tail(12);
  joint_pos_init_.setZero(n_joints_);

  p_gain_.tail(n_joints_).setConstant(joint_p_gain);
  d_gain_.tail(n_joints_).setConstant(joint_d_gain);

  gc_.setZero(19);
  gv_.setZero(18);
  linAccB_.setZero(3);
  angVelB_.setZero(3);
  quat_.setZero(4);

  logIdx_ = dataLogger_.initializeAnotherDataGroup(
      "raisin_example_controller",
      "p_gain_", p_gain_,
      "d_gain_", d_gain_,
      "p_target_", p_target_,
      "d_target_", d_target_,
      "gc_", gc_,
      "gv_", gv_,
      "linAccB_", linAccB_,
      "angVelB_", angVelB_,
      "quat_", quat_,
      "loopTime_", loopTime_
  );

  return true;
}

bool raiboEmptyController::init() {
  return true;
}

bool raiboEmptyController::advance() {
  auto sectionTimer = SectionTimer(); // feature to measure elapsed time

  // you can get sensor measurements and estimated states
  auto imu = robotHub_->getSensorSet("base_imu")->getSensor<raisim::InertialMeasurementUnit>("imu");
  imu->lockMutex();
  linAccB_ = imu->getLinearAcceleration();
  angVelB_ = imu->getAngularVelocity();
  quat_ = imu->getOrientation().e();
  imu->unlockMutex();

  robotHub_->lockMutex();
  robotHub_->getState(gc_, gv_);
  robotHub_->unlockMutex();

  // set pd target for the robot
  robotHub_->lockMutex();
  robotHub_->setPdTarget(p_target_, d_target_);
  robotHub_->unlockMutex();

  dataLogger_.append(
          logIdx_, p_gain_, d_gain_, p_target_, d_target_, gc_, gv_, linAccB_, angVelB_, quat_, loopTime_);

  return true;
}

bool raiboEmptyController::reset() {
  return true;
}

bool raiboEmptyController::terminate() {
  return true;
}

bool raiboEmptyController::stop() {
  return true;
}

// you can receive command from external source(joy pad...)
void raiboEmptyController::commandCallback(const raisin_interfaces::msg::Command::SharedPtr msg) {
  command_ << msg->x_vel, msg->y_vel, msg->yaw_rate;
}

extern "C" Controller * create(
    raisim::World & world, raisim::RaisimServer & server,
    raisim::World & worldSim, raisim::RaisimServer & serverSim, GlobalResource & globalResource)
{
  return new raiboEmptyController(world, server, worldSim, serverSim, globalResource);
}

extern "C" void destroy(Controller *p) {
  delete p;
}

} // namespace controller

} // namespace raisin
