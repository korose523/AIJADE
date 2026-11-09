using Aijade.Client.Settings;

using Microsoft.JSInterop;

namespace Aijade.UI.Services;

/// <summary>Account/character notebooks and media in IndexedDB; settings retain their existing store.</summary>
public sealed class BrowserCompanionStore(IJSRuntime js) : IKeyValueStore, IAsyncDisposable
{
    private IJSObjectReference? module;
    private async ValueTask<IJSObjectReference> ModuleAsync() => module ??= await js.InvokeAsync<IJSObjectReference>("import", "./_content/Aijade.UI/companion-store.js");
    public async ValueTask<string?> GetAsync(string key) => await (await ModuleAsync().ConfigureAwait(false)).InvokeAsync<string?>("get", key).ConfigureAwait(false);
    public async ValueTask SetAsync(string key, string value) => await (await ModuleAsync().ConfigureAwait(false)).InvokeVoidAsync("set", key, value).ConfigureAwait(false);
    public async ValueTask RemoveAsync(string key) => await (await ModuleAsync().ConfigureAwait(false)).InvokeVoidAsync("remove", key).ConfigureAwait(false);
    public async ValueTask DisposeAsync()
    {
        if (module is not null)
            await module.DisposeAsync().ConfigureAwait(false);
    }
}
