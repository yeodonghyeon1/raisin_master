// Copyright (c) 2025 Raion Robotics Inc.
//
// Any unauthorized copying, alteration, distribution, transmission,
// performance, display or use of this material is prohibited.
//
// All rights reserved.

#ifndef RAISIN_EMPTY_PLUGIN_HPP_
#define RAISIN_EMPTY_PLUGIN_HPP_

#include "raisin_plugin/plugin.hpp"

namespace raisin
{

namespace plugin
{

class EmptyPlugin : public Plugin, Node
{

public:
  EmptyPlugin(
    raisim::World & world, raisim::RaisimServer & server,
    raisim::World & worldSim, raisim::RaisimServer & serverSim, GlobalResource & globalResource);
  ~EmptyPlugin();
  bool init() final;
  bool advance() final;
  bool reset() final;

private:
};

} // namespace plugin

} // namespace raisin

#endif // RAISIN_EMPTY_PLUGIN_HPP_
