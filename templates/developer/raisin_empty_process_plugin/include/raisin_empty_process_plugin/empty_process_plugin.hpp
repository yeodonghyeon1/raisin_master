// Copyright (c) 2025 Raion Robotics Inc.
//
// Any unauthorized copying, alteration, distribution, transmission,
// performance, display or use of this material is prohibited.
//
// All rights reserved.

#ifndef RAISIN_empty_process_PLUGIN_HPP_
#define RAISIN_empty_process_PLUGIN_HPP_

#include "raisin_plugin/plugin.hpp"
#include "raisin_plugin/process.hpp"

namespace raisin
{

namespace plugin
{

class empty_processPlugin : public Plugin, Node
{

public:
  empty_processPlugin(
    raisim::World & world, raisim::RaisimServer & server,
    raisim::World & worldSim, raisim::RaisimServer & serverSim, GlobalResource & globalResource);
  ~empty_processPlugin();
  bool init() final;
  bool advance() final;
  bool reset() final;
  bool shouldTerminate() final;

private:
  Process process_;
};

} // namespace plugin

} // namespace raisin

#endif // RAISIN_empty_process_PLUGIN_HPP_
