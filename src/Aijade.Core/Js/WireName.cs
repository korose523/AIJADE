using System.Text;

namespace Aijade.Core.Js;

/// <summary>Wire names of enum values: PascalCase members map to their snake_case wire strings.</summary>
public static class WireName
{
    /// <summary><c>LongTerm</c> → <c>long_term</c>, <c>WMaxBelowTheta</c> → <c>w_max_below_theta</c>.</summary>
    public static string Of<T>(T value) where T : struct, Enum => Snake(value.ToString());

    public static string Snake(string pascal)
    {
        var sb = new StringBuilder(pascal.Length + 4);
        for (var i = 0; i < pascal.Length; i++)
        {
            var c = pascal[i];
            if (char.IsUpper(c))
            {
                if (i > 0)
                    sb.Append('_');
                sb.Append(char.ToLowerInvariant(c));
            }
            else
            {
                sb.Append(c);
            }
        }
        return sb.ToString();
    }

    /// <summary>The enum member whose wire name is <paramref name="wire"/>.</summary>
    public static T Parse<T>(string wire) where T : struct, Enum =>
        Enum.GetValues<T>().First(v => Of(v) == wire);
}
