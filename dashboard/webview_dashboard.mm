#import <Cocoa/Cocoa.h>
#import <WebKit/WebKit.h>

@interface AppDelegate : NSObject <NSApplicationDelegate, NSWindowDelegate>
@property(nonatomic, strong) NSWindow *window;
@property(nonatomic, strong) WKWebView *webView;
@property(nonatomic, copy) NSString *urlString;
@end

@implementation AppDelegate

- (instancetype)initWithURL:(NSString *)url {
  self = [super init];
  if (self) {
    _urlString = [url copy];
  }
  return self;
}

- (void)applicationDidFinishLaunching:(NSNotification *)notification {
  (void)notification;

  NSRect frame = NSMakeRect(0, 0, 1280, 820);
  self.window = [[NSWindow alloc] initWithContentRect:frame
                                            styleMask:(NSWindowStyleMaskTitled |
                                                       NSWindowStyleMaskClosable |
                                                       NSWindowStyleMaskMiniaturizable |
                                                       NSWindowStyleMaskResizable)
                                              backing:NSBackingStoreBuffered
                                                defer:NO];
  [self.window setTitle:@"Mini-Pupper Mission Dashboard"];
  [self.window center];

  WKWebViewConfiguration *config = [[WKWebViewConfiguration alloc] init];
  self.webView = [[WKWebView alloc] initWithFrame:frame configuration:config];
  [self.window setContentView:self.webView];
  [self.window makeKeyAndOrderFront:nil];
  [self.window setDelegate:self];

  NSURL *url = [NSURL URLWithString:self.urlString];
  if (url) {
    NSURLRequest *request = [NSURLRequest requestWithURL:url];
    [self.webView loadRequest:request];
  }
}

- (BOOL)applicationShouldTerminateAfterLastWindowClosed:(NSApplication *)sender {
  (void)sender;
  return YES;
}

@end

int main(int argc, char *argv[]) {
  @autoreleasepool {
    NSString *url = @"http://127.0.0.1:8000/index.html?apiPort=8443";
    if (argc >= 2 && argv[1] && argv[1][0] != '\0') {
      url = [NSString stringWithUTF8String:argv[1]];
    }

    NSApplication *app = [NSApplication sharedApplication];
    AppDelegate *delegate = [[AppDelegate alloc] initWithURL:url];
    [app setDelegate:delegate];
    [app run];
  }
  return 0;
}

