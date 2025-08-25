// Copyright (c) 2025 Raion Robotics Inc.
//
// Any unauthorized copying, alteration, distribution, transmission,
// performance, display or use of this material is prohibited.
//
// All rights reserved.

#ifndef RAISIN_EMPTYNODE__EMPTYNODE_HPP_
#define RAISIN_EMPTYNODE__EMPTYNODE_HPP_

#include "raisin_network/node.hpp"
#include "std_msgs/msg/string.hpp"
#include "std_srvs/srv/set_bool.hpp"

namespace raisin
{

class EmptySc : public Node {

 public:
  EmptySc(std::shared_ptr<Network> network, std::shared_ptr<Remote::Connection> connection);
  ~EmptySc();

  void messageCallback(std_msgs::msg::String::SharedPtr message);

 private:
  Subscriber<std_msgs::msg::String>::SharedPtr stringSubscriber_;
  Service<std_srvs::srv::SetBool>::SharedPtr setBoolService_;
  Client<std_srvs::srv::SetBool>::SharedPtr stringClient_;
  Client<std_srvs::srv::SetBool>::SharedFuture future_;
};

}  // namespace raisin

#endif  // RAISIN_EMPTYNODE__EMPTYNODE_HPP_
