// Copyright (c) 2025 Raion Robotics Inc.
//
// Any unauthorized copying, alteration, distribution, transmission,
// performance, display or use of this material is prohibited.
//
// All rights reserved.

#include "raisin_gui_empty_window/raisin_gui_empty_window.hpp"

namespace raisin
{

emptyWindow::emptyWindow(const std::string & titleIn, std::shared_ptr<GuiResource> guiResource)
: GuiWindow(titleIn, guiResource), Node(guiResource->network)
{
}

bool emptyWindow::update()
{
  return true;
}

bool emptyWindow::init()
{
  return true;
}

bool emptyWindow::draw()
{
  if (!open) {return true;}

  if (ImGui::Begin("empty window", &open)) {
    ImGui::Text("empty window");
  }
  ImGui::End();
  return open;
}

bool emptyWindow::reset()
{
  return true;
}

bool emptyWindow::shutDown()
{
  return true;
}


extern "C" GuiWindow * create(const std::string & titleIn, std::shared_ptr<GuiResource> guiResource)
{
  return new emptyWindow(titleIn, guiResource);
}

extern "C" void destroy(GuiWindow * p)
{
  delete p;
}

}
