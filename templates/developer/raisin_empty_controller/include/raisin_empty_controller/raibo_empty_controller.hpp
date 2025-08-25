// Copyright (c) 2024 Raion Robotics, Inc.
//
// Any unauthorized copying, alteration, distribution, transmission,
// performance, display or use of this material is prohibited.
//
// All rights reserved.

//
// Created by suyoung on 8/20/24.
//

#ifndef _RAIBO_EMPTY_CONTROLLER_HPP
#define _RAIBO_EMPTY_CONTROLLER_HPP

#include "raisim/World.hpp"
#include "raisin_parameter/parameter_container.hpp"
#include "raisin_controller/controller.hpp"
#include "raisin_data_logger/raisin_data_logger.hpp"

namespace raisin
{

namespace controller
{

class raiboEmptyController : public Controller
{
public:
  raiboEmptyController(
    raisim::World & world, raisim::RaisimServer & server,
    raisim::World & worldSim, raisim::RaisimServer & serverSim, GlobalResource & globalResource);
  bool create() final;
  bool init() final;
  bool advance() final;
  bool reset() final;
  bool terminate() final;
  bool stop() final;
  bool isDone() final;
  void commandCallback(const raisin_interfaces::msg::Command::SharedPtr msg);


private:
  parameter::ParameterContainer & param_;
  Eigen::Vector3f command_;

  int n_joints_;
  bool done_;

  uint64_t clk_;
  uint64_t one_sec_clk_;

  Eigen::VectorXd p_gain_;
  Eigen::VectorXd d_gain_;
  Eigen::VectorXd p_target_;
  Eigen::VectorXd d_target_;
  Eigen::VectorXd joint_pos_init_;

  Eigen::VectorXd gc_;
  Eigen::VectorXd gv_;
  Eigen::VectorXd linAccB_;
  Eigen::VectorXd angVelB_;
  Eigen::VectorXd quat_;

  double loopTime_;

  size_t logIdx_;
};

} // namespace controller

} // namespace raisin

#endif //RAIBO_JOINT_TEST_CONTROLLER_HPP
