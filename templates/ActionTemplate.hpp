// Copyright (c) 2024 Raion Robotics Inc.
//
// Any unauthorized copying, alteration, distribution, transmission,
// performance, display or use of this material is prohibited.
//
// All rights reserved.

#ifndef RAISIN_@@PROJECT_NAME@@_@@MESSAGE_NAME@@_HPP_
#define RAISIN_@@PROJECT_NAME@@_@@MESSAGE_NAME@@_HPP_

#include <vector>
#include <string>
#include <array>
#include <memory>
#include <cstdint>
#include "../msg/@@LOWER_MESSAGE_NAME@@_goal.hpp"
#include "../msg/@@LOWER_MESSAGE_NAME@@_result.hpp"
#include "../msg/@@LOWER_MESSAGE_NAME@@_feedback.hpp"
#include "../msg/@@LOWER_MESSAGE_NAME@@_feedback_message.hpp"
#include "../srv/@@LOWER_MESSAGE_NAME@@_get_result.hpp"
#include "../srv/@@LOWER_MESSAGE_NAME@@_send_goal.hpp"
#include "action_msgs/msg/goal_status.hpp"
#include "action_msgs/msg/goal_status_array.hpp"
#include "action_msgs/srv/cancel_goal.hpp"

namespace raisin {
namespace @@PROJECT_NAME@@::action {

class @@MESSAGE_NAME@@ {
public:

inline static std::string getDataType() {
  return "@@PROJECT_NAME@@::action::@@MESSAGE_NAME@@";
}

using Goal = @@PROJECT_NAME@@::msg::@@MESSAGE_NAME@@Goal;
using Result = @@PROJECT_NAME@@::msg::@@MESSAGE_NAME@@Result;
using SendGoalService = @@PROJECT_NAME@@::srv::@@MESSAGE_NAME@@SendGoal;
using GetResultService = @@PROJECT_NAME@@::srv::@@MESSAGE_NAME@@GetResult;
using CancelGoalService = action_msgs::srv::CancelGoal;
using Feedback = @@PROJECT_NAME@@::msg::@@MESSAGE_NAME@@Feedback;
using FeedbackMessage = @@PROJECT_NAME@@::msg::@@MESSAGE_NAME@@FeedbackMessage;
using GoalStatus = action_msgs::msg::GoalStatus;
using GoalStatusMessage = action_msgs::msg::GoalStatusArray;

using ConstSharedPtr = std::shared_ptr<const @@PROJECT_NAME@@::action::@@MESSAGE_NAME@@>;
using SharedPtr = std::shared_ptr<@@PROJECT_NAME@@::action::@@MESSAGE_NAME@@>;
using ConstUniquePtr = std::unique_ptr<const @@PROJECT_NAME@@::action::@@MESSAGE_NAME@@>;
using UniquePtr = std::unique_ptr<@@PROJECT_NAME@@::action::@@MESSAGE_NAME@@>;
};

} // namespace @@PROJECT_NAME@@::action
} // raisin


#endif //RAISIN_@@PROJECT_NAME@@_@@MESSAGE_NAME@@_HPP_