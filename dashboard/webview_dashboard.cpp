#include <cstdlib>
#include <string>

#include "webview.h"

int main(int argc, char **argv) {
  std::string url = "http://127.0.0.1:8000/index.html?apiPort=8443";
  if (argc >= 2 && argv[1] && argv[1][0] != '\0') {
    url = argv[1];
  }

  // Non-debug mode (0). This opens a native webview window.
  webview::webview w(false, nullptr);
  w.set_title("Mini-Pupper Mission Dashboard");
  w.set_size(1280, 820, WEBVIEW_HINT_NONE);
  w.navigate(url);
  w.run();
  return 0;
}

