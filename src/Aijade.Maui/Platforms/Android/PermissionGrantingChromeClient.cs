using Android.Webkit;

using WebView = Android.Webkit.WebView;

namespace Aijade.Maui.Platforms.Android;

/// <summary>
/// Wraps BlazorWebView's own WebChromeClient (everything is delegated to it) and answers the page's microphone / camera
/// requests: each is granted only if the user grants the matching Android runtime permission, and only for the resources
/// that permission covers. Anything else the page asks for is denied.
/// </summary>
public sealed class PermissionGrantingChromeClient(WebChromeClient inner) : WebChromeClient
{
    public override void OnPermissionRequest(PermissionRequest? request)
    {
        if (request?.GetResources() is not { } resources)
            return;
        MainThread.BeginInvokeOnMainThread(async () =>
        {
            var granted = new List<string>();
            foreach (var resource in resources)
            {
                var ok = resource switch
                {
                    PermissionRequest.ResourceAudioCapture => await Permissions.RequestAsync<Permissions.Microphone>() == PermissionStatus.Granted,
                    PermissionRequest.ResourceVideoCapture => await Permissions.RequestAsync<Permissions.Camera>() == PermissionStatus.Granted,
                    _ => false,
                };
                if (ok)
                    granted.Add(resource);
            }
            if (granted.Count > 0)
                request.Grant([.. granted]);
            else
                request.Deny();
        });
    }

    public override void OnPermissionRequestCanceled(PermissionRequest? request) => inner.OnPermissionRequestCanceled(request);

    public override bool OnCreateWindow(WebView? view, bool isDialog, bool isUserGesture, global::Android.OS.Message? resultMsg) =>
        inner.OnCreateWindow(view, isDialog, isUserGesture, resultMsg);

    public override void OnCloseWindow(WebView? window) => inner.OnCloseWindow(window);

    public override bool OnShowFileChooser(WebView? webView, IValueCallback? filePathCallback, FileChooserParams? fileChooserParams) =>
        inner.OnShowFileChooser(webView, filePathCallback, fileChooserParams);

    public override bool OnJsAlert(WebView? view, string? url, string? message, JsResult? result) => inner.OnJsAlert(view, url, message, result);

    public override bool OnJsConfirm(WebView? view, string? url, string? message, JsResult? result) => inner.OnJsConfirm(view, url, message, result);

    public override bool OnJsPrompt(WebView? view, string? url, string? message, string? defaultValue, JsPromptResult? result) =>
        inner.OnJsPrompt(view, url, message, defaultValue, result);

    public override bool OnConsoleMessage(ConsoleMessage? consoleMessage) => inner.OnConsoleMessage(consoleMessage);

    public override void OnProgressChanged(WebView? view, int newProgress) => inner.OnProgressChanged(view, newProgress);
}
