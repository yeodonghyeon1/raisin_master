// Copyright (c) 2025 Raion Robotics Inc.
//
// Any unauthorized copying, alteration, distribution, transmission,
// performance, display or use of this material is prohibited.
//
// All rights reserved.

// raisin inclusion
#include "raisin_empty_node/raisin_empty_subscriber_client.hpp"

// std inclusion
#include <string>

using namespace std::chrono_literals;

namespace raisin
{

EmptySc::EmptySc(std::shared_ptr<Network> network, std::shared_ptr<Remote::Connection> connection) :
  Node(network) {

  // create publisher
  stringSubscriber_ = createSubscriber<std_msgs::msg::String>("string_message", connection,
                      std::bind(&EmptySc::messageCallback, this, std::placeholders::_1), "sc");

  // create Service
  stringClient_ = createClient<std_srvs::srv::SetBool>("set_bool_service", connection, "sc");
  createTimedLoop("request_repeat", [this](){
      if (stringClient_ && stringClient_->isServiceAvailable()) {
        if (!future_.valid()) {
          auto req = std::make_shared<std_srvs::srv::SetBool::Request>();
          req->data = true;
          future_ = stringClient_->asyncSendRequest(req);
          std::cout << "sent request " << std::endl;
        }

        if (future_.valid() && future_.wait_for(0s) == std::future_status::ready) {
          auto response = future_.get();
          future_ = {};
          std::cout << "response: " << response->message << std::endl;
        }
      }
    }
  , 1.);
}

EmptySc::~EmptySc() {
  /// YOU MUST CALL THIS METHOD IN ALL NODES
  cleanupResources();
}

void EmptySc::messageCallback(std_msgs::msg::String::SharedPtr message) {
  std::cout<<"message: "<<message->data<<std::endl;
}

}  // namespace raisin