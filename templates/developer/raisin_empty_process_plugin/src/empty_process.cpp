// Copyright (c) 2025 Raion Robotics Inc.
//
// Any unauthorized copying, alteration, distribution, transmission,
// performance, display or use of this material is prohibited.
//
// All rights reserved.
//

#include "raisin_network/raisin.hpp"
#include "std_msgs/msg/string.hpp"
#include "raisin_network/raisin.hpp"
#include <iostream>

using namespace raisin;

const char* shm_name = "my_shared_memory2";

class PublisherNode : public raisin::Node
{
 public:
  explicit PublisherNode(std::shared_ptr<raisin::ThreadPool> pool)
      : Node(pool)
  {
    publisher_ = createPublisher<raisin::std_msgs::msg::String>("my_topic");

    createTimedLoop("publish_loop", [this]() {
      static int version = 0;
      raisin::std_msgs::msg::String msg;
      msg.data = "hello world " + std::to_string(version++);
      publisher_->publish(msg);
    }, 10.);  // 1 Hz
  }

  ~PublisherNode() {
    cleanupResources();
  }

 private:
  raisin::Publisher<raisin::std_msgs::msg::String>::SharedPtr publisher_;
};

int main() {
  raisinInit();
  std::vector<std::vector<std::string>> thread_spec = {{std::string("main")}};
  auto pool = std::make_shared<raisin::ThreadPool>(thread_spec, false);
  PublisherNode node(pool);

  pool->getWorker(0)->run();

  return 0;
}