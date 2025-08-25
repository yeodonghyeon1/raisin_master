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

class EmptyPs : public Node {

 public:
  EmptyPs(std::shared_ptr<Network> network);
  ~EmptyPs();

  void responseCallback(std_srvs::srv::SetBool::Request::SharedPtr request,
                        std_srvs::srv::SetBool::Response::SharedPtr response);

 private:
  Publisher<std_msgs::msg::String>::SharedPtr stringPublisher_;
  Service<std_srvs::srv::SetBool>::SharedPtr setBoolService_;
};

}  // namespace raisin

#endif  // RAISIN_EMPTYNODE__EMPTYNODE_HPP_
