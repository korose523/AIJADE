using System.Globalization;
using System.Net.Http.Headers;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

using Aijade.Client.Companion;

namespace Aijade.Integrations;

public sealed class OneBotSendException(DeliveryReceipt receipt) : HttpRequestException($"NapCat send_private_msg: {receipt.Outcome} (HTTP {receipt.HttpStatus})")
{
    public DeliveryReceipt Receipt { get; } = receipt;
}

public sealed partial class OneBotConnector
{
    private int rejected, unknown, deliveryRecordFailures;
    private sealed class DeliverySession(ICompanionDelivery store, string id)
    {
        public ICompanionDelivery Store { get; } = store;
        public string Id { get; } = id;
        public int NextPart { get; set; }
    }

    private async Task PostSegmentsAsync(JsonArray segments, CancellationToken ct, DeliverySession? delivery = null, string kind = "text")
    {
        var payload = new JsonObject { ["user_id"] = long.Parse(owner, CultureInfo.InvariantCulture), ["message"] = segments }.ToJsonString();
        var index = delivery?.NextPart ?? 0;
        if (delivery is not null)
        {
            try
            {
                var part = await delivery.Store.StartDeliveryPartAsync(delivery.Id, index, kind,
                    Convert.ToHexStringLower(SHA256.HashData(Encoding.UTF8.GetBytes(payload))), ct).ConfigureAwait(false);
                if (!part.Created) throw new InvalidOperationException("This outbound part already has an attempt; it will not be resent");
                delivery.NextPart++;
            }
            catch (Exception e) when (e is Aijade.Client.Api.AijadeApiException or HttpRequestException or OperationCanceledException)
            {
                Interlocked.Increment(ref deliveryRecordFailures); throw;
            }
        }
        DeliveryReceipt receipt;
        try
        {
            using var request = new HttpRequestMessage(HttpMethod.Post, new Uri(napcat, "send_private_msg"))
                { Content = new StringContent(payload, Encoding.UTF8, "application/json") };
            request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", token);
            using var response = await http.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, ct).ConfigureAwait(false);
            receipt = await ReadSendReceiptAsync(response, ct).ConfigureAwait(false);
            if (receipt.Outcome != "acknowledged") throw new OneBotSendException(receipt);
        }
        catch (OneBotSendException e)
        {
            if (e.Receipt.Outcome == "rejected") Interlocked.Increment(ref rejected); else Interlocked.Increment(ref unknown);
            await ObserveDeliveryAsync(delivery, index, e.Receipt).ConfigureAwait(false);
            throw;
        }
        catch (Exception e) when (e is HttpRequestException or OperationCanceledException or IOException)
        {
            Interlocked.Increment(ref unknown);
            await ObserveDeliveryAsync(delivery, index, new("unknown")).ConfigureAwait(false);
            throw;
        }
        Interlocked.Increment(ref answered); // counts validated API acknowledgements, never user read receipts
        await ObserveDeliveryAsync(delivery, index, receipt).ConfigureAwait(false);
    }

    private async Task ObserveDeliveryAsync(DeliverySession? delivery, int index, DeliveryReceipt receipt)
    {
        if (delivery is null) return;
        try
        {
            using var cleanup = new CancellationTokenSource(TimeSpan.FromSeconds(3));
            await delivery.Store.CompleteDeliveryPartAsync(delivery.Id, index, receipt, cleanup.Token).ConfigureAwait(false);
        }
        catch (Exception e) when (e is Aijade.Client.Api.AijadeApiException or HttpRequestException or OperationCanceledException)
        {
            Interlocked.Increment(ref deliveryRecordFailures);
            throw; // no next outbound part when its predecessor's observation cannot be persisted
        }
    }

    private static async Task<DeliveryReceipt> ReadSendReceiptAsync(HttpResponseMessage response, CancellationToken ct)
    {
        var status = (int)response.StatusCode;
        const int maximum = 64 * 1024;
        if (response.Content.Headers.ContentLength > maximum) return new("unknown", HttpStatus: status);
        await using var stream = await response.Content.ReadAsStreamAsync(ct).ConfigureAwait(false);
        using var bytes = new MemoryStream(); var buffer = new byte[8192]; int read;
        while ((read = await stream.ReadAsync(buffer, ct).ConfigureAwait(false)) > 0)
        {
            if (bytes.Length + read > maximum) return new("unknown", HttpStatus: status);
            bytes.Write(buffer, 0, read);
        }
        JsonObject? answer;
        try { answer = JsonNode.Parse(bytes.ToArray()) as JsonObject; }
        catch (JsonException) { return new("unknown", HttpStatus: status); }
        var code = answer?["retcode"] is JsonValue r && r.TryGetValue<int>(out var n) ? (int?)n : null;
        var state = Text(answer?["status"]);
        if (status is >= 400 and < 500 and not 408 || response.IsSuccessStatusCode && state == "failed" && code is not null and not 0 and not 1)
            return new("rejected", HttpStatus: status, Retcode: code);
        if (response.IsSuccessStatusCode && state == "ok" && code == 0 && answer?["data"] is JsonObject data && data["message_id"] is JsonValue id)
        {
            if (id.TryGetValue<long>(out var number) || id.TryGetValue<string>(out var text) && long.TryParse(text, NumberStyles.AllowLeadingSign, CultureInfo.InvariantCulture, out number))
                return new("acknowledged", number.ToString(CultureInfo.InvariantCulture), status, code);
        }
        return new("unknown", HttpStatus: status, Retcode: code);
    }
}
