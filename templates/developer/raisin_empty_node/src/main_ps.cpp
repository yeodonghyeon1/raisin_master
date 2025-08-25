// Copyright (c) 2025 Raion Robotics Inc.
//
// Any unauthorized copying, alteration, distribution, transmission,
// performance, display or use of this material is prohibited.
//
// All rights reserved.

#include "raisin_empty_node/raisin_empty_publisher_service.hpp"
#include "raisin_network/raisin.hpp"

using namespace raisin;

int main() {
  raisinInit();
  std::vector<std::vector<std::string>> thread_spec = {{std::string("ps")}};
  auto network = std::make_shared<Network>("publisherAndService", "tutorial", thread_spec);
  network->launchServer(Remote::NetworkType::TCP);

  EmptyPs ps(network);

  std::this_thread::sleep_for(std::chrono::seconds(20));
  return 0;
}