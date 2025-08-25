// Copyright (c) 2025 Raion Robotics Inc.
//
// Any unauthorized copying, alteration, distribution, transmission,
// performance, display or use of this material is prohibited.
//
// All rights reserved.

#ifndef RAISIN_GUI_empty_PLUGIN_HPP_
#define RAISIN_GUI_empty_PLUGIN_HPP_

#include <mutex>
#include <string>
#include <atomic>

#include "imgui/imgui.h"
#include "raisin_gui_base/raisin_gui_window.hpp"

// raisin include
#include "raisin_parameter/parameter_container.hpp"
#include "raisin_data_logger/raisin_data_logger.hpp"
#include "raisin_data_logger/raisin_timer.hpp"
#include "raisin_network/node.hpp"


namespace raisin
{

class emptyWindow : public GuiWindow, public Node
{
public:
  emptyWindow(const std::string & titleIn, std::shared_ptr<GuiResource> guiResource);
  ~emptyWindow() { cleanupResources(); }

  bool update() final;
  bool init() final;
  bool draw() final;
  bool shutDown() final;
  bool reset() final;

protected:
};

}
#endif  // RAISIN_GUI_ROBOT_SELECTION_PLUGIN_HPP_
