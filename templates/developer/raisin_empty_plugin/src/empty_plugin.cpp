// Copyright (c) 2020 Robotics and Artificial Intelligence Lab, KAIST
//
// Any unauthorized copying, alteration, distribution, transmission,
// performance, display or use of this material is prohibited.
//
// All rights reserved.

#include "raisin_empty_plugin/empty_plugin.hpp"

namespace raisin
{

namespace plugin
{

EmptyPlugin::EmptyPlugin(
  raisim::World & world, raisim::RaisimServer & server,
  raisim::World & worldSim, raisim::RaisimServer & serverSim, GlobalResource & globalResource)
: Node(globalResource.network), Plugin(world, server, worldSim, serverSim, globalResource)
{
  pluginType_ = PluginType::CUSTOM;
}

EmptyPlugin::~EmptyPlugin()
{
  cleanupResources();
}

bool EmptyPlugin::init()
{
  return true;
}

bool EmptyPlugin::advance()
{
  return true;
}

bool EmptyPlugin::reset()
{
  return true;
}

extern "C" Plugin * create(
  raisim::World & world, raisim::RaisimServer & server,
  raisim::World & worldSim, raisim::RaisimServer & serverSim, GlobalResource & globalResource)
{
  return new EmptyPlugin(world, server, worldSim, serverSim, globalResource);
}

extern "C" void destroy(EmptyPlugin * p)
{
  delete p;
}

} // namespace plugin

} // namespace raisin
