// Copyright (c) 2025 Raion Robotics Inc.
//
// Any unauthorized copying, alteration, distribution, transmission,
// performance, display or use of this material is prohibited.
//
// All rights reserved.

// raisin inclusion
#include "raisin_empty_node/raisin_empty_publisher_service.hpp"

// std inclusion
#include <string>

namespace raisin
{

EmptyPs::EmptyPs(std::shared_ptr<Network> network) :
  Node(network) {

  // create publisher
  stringPublisher_ = createPublisher<std_msgs::msg::String>("string_message");
  createTimedLoop("string_message", [this](){
    std_msgs::msg::String msg;
    msg.data = "raisin publisher!";
    stringPublisher_->publish(msg);
  }, 1., "ps");

  // create Service
  setBoolService_ = createService<std_srvs::srv::SetBool>("set_bool_service",
                      std::bind(&EmptyPs::responseCallback, this, std::placeholders::_1, std::placeholders::_2), "ps");
}

EmptyPs::~EmptyPs() {
  /// YOU MUST CALL THIS METHOD IN ALL NODES
  cleanupResources();
}

void EmptyPs::responseCallback(std_srvs::srv::SetBool::Request::SharedPtr request,
                               std_srvs::srv::SetBool::Response::SharedPtr response) {
  response->success = true;
  response->message = "raisin service!";
}

}  // namespace raisin