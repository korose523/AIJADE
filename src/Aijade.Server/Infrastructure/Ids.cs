using System.Security.Cryptography;

namespace Aijade.Server.Infrastructure;

/// <summary>Random 21-character URL-safe ids (126 bits), the format the server uses for every generated primary key.</summary>
public static class Ids
{
    private const string Alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz_-";

    public static string New(int size = 21)
    {
        Span<byte> bytes = stackalloc byte[size];
        RandomNumberGenerator.Fill(bytes);
        var chars = new char[size];
        for (var i = 0; i < size; i++)
            chars[i] = Alphabet[bytes[i] & 63];
        return new string(chars);
    }
}
