// Copyright (c) 2025 Raion Robotics Inc.
//
// Any unauthorized copying, alteration, distribution, transmission,
// performance, display or use of this material is prohibited.
//
// All rights reserved.

#include "raisin_empty_process_plugin/empty_process_plugin.hpp"

namespace raisin
{

namespace plugin
{

empty_processPlugin::empty_processPlugin(
  raisim::World & world, raisim::RaisimServer & server,
  raisim::World & worldSim, raisim::RaisimServer & serverSim, GlobalResource & globalResource)
: Node(globalResource.network), Plugin(world, server, worldSim, serverSim, globalResource),
  process_("raisin_empty_process_plugin", "raisin_empty_process_plugin_process")
{
  pluginType_ = PluginType::CUSTOM;
}

empty_processPlugin::~empty_processPlugin()
{
  cleanupResources();
}

bool empty_processPlugin::init()
{
  return true;
}

bool empty_processPlugin::advance()
{
  return true;
}

bool empty_processPlugin::reset()
{
  return true;
}

bool empty_processPlugin::shouldTerminate()
{
  return !process_.isAlive();
}


extern "C" Plugin * create(
  raisim::World & world, raisim::RaisimServer & server,
  raisim::World & worldSim, raisim::RaisimServer & serverSim, GlobalResource & globalResource)
{
  return new empty_processPlugin(world, server, worldSim, serverSim, globalResource);
}

extern "C" void destroy(empty_processPlugin * p)
{
  delete p;
}

} // namespace plugin

} // namespace raisin
