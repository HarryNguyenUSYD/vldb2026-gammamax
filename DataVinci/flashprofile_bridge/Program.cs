using System.Reflection;
using System.Text.Json;
using System.Text.Json.Serialization;
using System.Text.RegularExpressions;
using Microsoft.ProgramSynthesis.Matching.Text;

internal sealed record PatternSpec(
    [property: JsonPropertyName("regex")] string? Regex,
    [property: JsonPropertyName("regexes_to_exclude")] string[]? RegexesToExclude,
    [property: JsonPropertyName("is_null")] bool IsNull);

internal sealed record Request(
    [property: JsonPropertyName("operation")] string? Operation,
    [property: JsonPropertyName("values")] string?[]? Values,
    [property: JsonPropertyName("patterns")] PatternSpec[]? Patterns);

internal sealed record PatternResult(
    [property: JsonPropertyName("display")] string Display,
    [property: JsonPropertyName("regex")] string? Regex,
    [property: JsonPropertyName("regexes_to_exclude")] string[] RegexesToExclude,
    [property: JsonPropertyName("matching_fraction")] double MatchingFraction,
    [property: JsonPropertyName("matched_indices")] int[] MatchedIndices,
    [property: JsonPropertyName("is_null")] bool IsNull,
    [property: JsonPropertyName("examples")] string[] Examples);

internal static class Program
{
    private static readonly TimeSpan RegexTimeout = TimeSpan.FromSeconds(5);

    public static int Main()
    {
        try
        {
            var request = JsonSerializer.Deserialize<Request>(Console.In.ReadToEnd(), JsonOptions())
                ?? throw new ArgumentException("stdin must contain a JSON object");
            var values = request.Values ?? throw new ArgumentException("values must be an array");
            var operation = request.Operation ?? "learn";
            object response = operation switch
            {
                "learn" => Learn(values),
                "match" => Match(values, request.Patterns
                    ?? throw new ArgumentException("match requires patterns")),
                _ => throw new ArgumentException($"unsupported operation: {operation}")
            };
            Console.Out.Write(JsonSerializer.Serialize(response, JsonOptions()));
            return 0;
        }
        catch (Exception error)
        {
            Console.Error.WriteLine($"FlashProfileBridge: {error.Message}");
            return 1;
        }
    }

    private static object Learn(string?[] values)
    {
        if (values.Length == 0) throw new ArgumentException("values must be non-empty");
        var session = new Session();
        session.Inputs.Add(values);
        var patterns = session.LearnPatterns().Select(pattern =>
        {
            var regex = pattern.IsNull ? null : pattern.Regex?.ToString();
            var exclusions = pattern.IsNull
                ? Array.Empty<string>()
                : pattern.RegexesToExclude.Select(value => value.ToString()).ToArray();
            return new PatternResult(
                pattern.Description ?? regex ?? "Null", regex, exclusions,
                pattern.MatchingFraction, MatchingIndices(values,
                    new PatternSpec(regex, exclusions, pattern.IsNull)),
                pattern.IsNull,
                pattern.Examples?.Where(value => value is not null).Cast<string>().ToArray()
                    ?? Array.Empty<string>());
        }).ToArray();
        return new { sdk_version = SdkVersion(), patterns };
    }

    private static object Match(string?[] values, PatternSpec[] patterns)
    {
        var matchedByPattern = patterns.Select(pattern => MatchingIndices(values, pattern)).ToArray();
        var accepted = matchedByPattern.SelectMany(indices => indices).Distinct().Order().ToArray();
        return new
        {
            sdk_version = SdkVersion(),
            matched_indices_by_pattern = matchedByPattern,
            accepted_indices = accepted
        };
    }

    private static int[] MatchingIndices(string?[] values, PatternSpec pattern) =>
        values.Select((value, index) => (value, index))
            .Where(item => Matches(item.value, pattern))
            .Select(item => item.index).ToArray();

    private static bool Matches(string? value, PatternSpec pattern)
    {
        if (pattern.IsNull) return value is null;
        if (value is null || pattern.Regex is null
            || !Regex.IsMatch(value, pattern.Regex, RegexOptions.None, RegexTimeout)) return false;
        return (pattern.RegexesToExclude ?? Array.Empty<string>()).All(exclusion =>
            !Regex.IsMatch(value, exclusion, RegexOptions.None, RegexTimeout));
    }

    private static string SdkVersion() =>
        typeof(Session).Assembly.GetCustomAttribute<AssemblyInformationalVersionAttribute>()?.InformationalVersion
        ?? typeof(Session).Assembly.GetName().Version?.ToString()
        ?? "unknown";

    private static JsonSerializerOptions JsonOptions() => new()
    {
        PropertyNameCaseInsensitive = true,
        WriteIndented = false
    };
}
