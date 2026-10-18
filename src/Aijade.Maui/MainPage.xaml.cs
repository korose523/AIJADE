namespace Aijade.Maui;

public partial class MainPage : ContentPage
{
    public MainPage()
    {
        InitializeComponent();
#if ANDROID
        // Microphone and camera requests from the page (voice input, vision, beat sync) go through Android's runtime
        // permissions instead of being silently refused by the web view.
        blazorWebView.BlazorWebViewInitialized += (_, e) =>
            e.WebView.SetWebChromeClient(new Platforms.Android.PermissionGrantingChromeClient(e.WebView.WebChromeClient!));
#endif
    }
}
