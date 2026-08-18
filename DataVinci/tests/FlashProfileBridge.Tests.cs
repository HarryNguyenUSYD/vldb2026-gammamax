// Contract smoke test source for environments with .NET 8 and restored PROSE packages.
// Python integration tests exercise DataVinci independently; README supplies the
// executable bridge smoke command because PROSE is a closed-source NuGet dependency.
using Microsoft.ProgramSynthesis.Matching.Text;
using Xunit;

public sealed class FlashProfileBridgeTests
{
    [Fact]
    public void OfficialProfilerReturnsPatterns()
    {
        var session = new Session();
        session.Inputs.Add(new[] { "US-123", "UK-392", "AU-211" });
        var patterns = session.LearnPatterns();
        Assert.NotEmpty(patterns);
        Assert.Contains(patterns, pattern => !pattern.IsNull && pattern.Regex is not null);
    }
}
