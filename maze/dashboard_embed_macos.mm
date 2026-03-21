#if defined(__APPLE__)

#import <Cocoa/Cocoa.h>
#import <WebKit/WebKit.h>

#include <SDL2/SDL.h>
#include <SDL2/SDL_syswm.h>

static WKWebView *g_embedded_webview = nil;

extern "C" int dashboard_embed_show(SDL_Window *window, const char *url_cstr) {
  if (!window || !url_cstr || !url_cstr[0]) return 0;

  SDL_SysWMinfo info;
  SDL_VERSION(&info.version);
  if (!SDL_GetWindowWMInfo(window, &info)) return 0;

  NSWindow *nswin = info.info.cocoa.window;
  if (!nswin) return 0;

  NSView *content = [nswin contentView];
  if (!content) return 0;

  if (!g_embedded_webview) {
    WKWebViewConfiguration *cfg = [[WKWebViewConfiguration alloc] init];
    g_embedded_webview = [[WKWebView alloc] initWithFrame:[content bounds] configuration:cfg];
    [g_embedded_webview setAutoresizingMask:(NSViewWidthSizable | NSViewHeightSizable)];
    [content addSubview:g_embedded_webview];
  } else if ([g_embedded_webview superview] != content) {
    [g_embedded_webview removeFromSuperview];
    [content addSubview:g_embedded_webview];
  }

  NSString *urlStr = [NSString stringWithUTF8String:url_cstr];
  NSURL *url = [NSURL URLWithString:urlStr];
  if (!url) return 0;

  NSURLRequest *req = [NSURLRequest requestWithURL:url];
  [g_embedded_webview setHidden:NO];
  [g_embedded_webview loadRequest:req];
  [g_embedded_webview removeFromSuperview];
  [content addSubview:g_embedded_webview positioned:NSWindowAbove relativeTo:nil];
  return 1;
}

extern "C" void dashboard_embed_hide(void) {
  if (g_embedded_webview) {
    [g_embedded_webview setHidden:YES];
  }
}

#endif

