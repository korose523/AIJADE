using Aijade.Client.Api;
using Aijade.Client.I18n;
using Aijade.Client.Settings;
using Aijade.UI;
using Aijade.UI.Services;

using Microsoft.AspNetCore.Components.Web;
using Microsoft.AspNetCore.Components.WebAssembly.Hosting;

var builder = WebAssemblyHostBuilder.CreateDefault(args);
builder.RootComponents.Add<Routes>("#app");
builder.RootComponents.Add<HeadOutlet>("head::after");

// The API is served from the same origin by default; a separate server can be set in wwwroot/appsettings.json (ApiBase).
var apiBase = builder.Configuration["ApiBase"] is { Length: > 0 } configured ? configured : builder.HostEnvironment.BaseAddress;
builder.Services.AddSingleton(new HttpClient { BaseAddress = new Uri(apiBase) });
builder.Services.AddSingleton<IClientHost>(new SameOriginHost(new Uri(apiBase)));
builder.Services.AddAijadeUi();

await builder.Build().RunAsync();
