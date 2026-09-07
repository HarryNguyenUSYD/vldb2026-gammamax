#pragma once
#include "gammamax/decision_tree.hpp"
#include "gammamax/numeric_candidates.hpp"
#include <cassert>
#include <limits>

inline void test_imputation() {
    using namespace gammamax;
    const TreeConfig small{5, 1, 16, 6};
    auto throws = [](auto operation) {
        bool caught = false;
        try { operation(); } catch (const std::runtime_error&) { caught = true; }
        assert(caught);
    };
    assert(is_missing("") && is_missing("?") && !is_missing("MISSING"));
    assert(!numeric_value("nan") && !numeric_value("inf") && !numeric_value("2x"));
    assert(!numeric_value("+-1") && !numeric_value("+") && numeric_value(" +1.25") == 1.25);
    assert((infer_tree_features({{"1", "A", "?"}, {"2", "B", ""}}) == std::vector<bool>{true, false, false}));
    throws([] { infer_tree_features({{"1", "2"}, {"3"}}); });
    assert(!DecisionTree({}, 0).predict({}).resolved);
    assert(!DecisionTree({{"?"}, {""}}, 0).predict({"?"}).resolved);
    throws([] { DecisionTree({{"1"}}, 1); });
    for (auto bad : {TreeConfig{6,1,16,6}, TreeConfig{5,0,16,6}, TreeConfig{5,1,0,6},
                     TreeConfig{5,1,33,6}, TreeConfig{5,1,16,16}})
        throws([&] { validate_tree_config(bad); });

    ImputationTable classification{{"1","A"},{"2","A"},{"9","B"},{"10","B"},{"8","?"}};
    DecisionTree classifier(classification, 1, small);
    assert(classifier.predict({"1","?"}).category == "A");
    assert(classifier.predict({"10","?"}).category == "B");
    assert(classifier.predict({"?","?"}).category == "A"); // Unseen missing branch: node mode.
    assert(classifier.depth() == 1 && classifier.training_rows() == 4);
    assert(classifier.predict({"10","invented target"}).category == "B");
    throws([&] { classifier.predict({"1"}); });

    DecisionTree categorical({{"red","2"},{"red","4"},{"blue","10"},{"blue","12"}}, 1, small);
    assert(categorical.predict({"red","?"}).number == 3);
    assert(categorical.predict({"blue","?"}).number == 11);
    assert(categorical.predict({"unseen","?"}).resolved);
    DecisionTree missing_category({{"?","A"},{"","A"},{"MISSING","B"},{"MISSING","B"}}, 1, small);
    assert(missing_category.predict({"?","?"}).category == "A");
    assert(missing_category.predict({"MISSING","?"}).category == "B");
    DecisionTree missing_number({{"1","A"},{"2","A"},{"8","B"},{"9","B"},{"?","C"},{"","C"}}, 1, small);
    assert(missing_number.predict({"?","?"}).category == "C");
    assert(missing_number.predict({"1","?"}).category == "A");
    assert(missing_number.predict({"9","?"}).category == "B");

    DecisionTree mean({{"2"},{"4"},{"?"}}, 0, small);
    assert(mean.predict({"?"}).number == 3 && mean.predict({"?"}).fallback);
    DecisionTree mode({{"B"},{"A"},{"?"}}, 0, small);
    assert(mode.predict({"?"}).category == "A");
    DecisionTree singleton({{"constant","7"},{"?","?"}}, 1, small);
    assert(singleton.predict({"?","?"}).number == 7);
    DecisionTree min_leaf(classification, 1, TreeConfig{5,3,16,6});
    assert(min_leaf.node_count() == 1 && min_leaf.predict({"10","?"}).fallback);
    DecisionTree zero_depth(classification, 1, TreeConfig{0,1,16,6});
    assert(zero_depth.depth() == 0 && zero_depth.node_count() == 1);
    DecisionTree huge({{"a","1e308"},{"b","-1e308"}}, 1, TreeConfig{0,1,16,6});
    assert(huge.predict({"a","?"}).number == 0);
    DecisionTree tiny({{"a","1e-300"},{"b","2e-300"}}, 1, small);
    assert(tiny.node_count() == 3);
    assert(tiny.predict({"a","?"}).number == 1e-300);
    assert(tiny.predict({"b","?"}).number == 2e-300);
    DecisionTree zeros({{"a","0"},{"b","0"}}, 1, small);
    assert(zeros.predict({"a","?"}).number == 0);
    DecisionTree too_small_missing({{"1","A"},{"2","A"},{"8","B"},{"9","B"},{"?","C"}}, 1, TreeConfig{5,2,16,6});
    assert(too_small_missing.node_count() == 1);
    ImputationTable many;
    for (int i=0; i<100; ++i) many.push_back({std::to_string(i),std::to_string(i)});
    DecisionTree bounded(many, 1, TreeConfig{2,5,1,6});
    assert(bounded.depth() <= 2 && bounded.node_count() <= 7);
    const auto frozen = classification;
    auto changed = classification;
    changed.back()[1] = classifier.predict(changed.back()).category;
    assert(classification == frozen && classifier.training_rows() == 4);
    DecisionTree repeat(classification, 1, small);
    assert(repeat.node_count() == classifier.node_count());
    for (const auto& row : classification) assert(repeat.predict(row).category == classifier.predict(row).category);

    assert((numeric_candidates(23.6784,6) == std::vector<std::string>{"23.6784","23.678","23.68","23.7","24"}));
    assert((numeric_candidates(1.249,2) == std::vector<std::string>{"1.249","1.25","1.2","1"}));
    struct CommaDecimal : std::numpunct<char> {
        char do_decimal_point() const override { return ','; }
    };
    const auto previous_locale = std::locale();
    std::locale::global(std::locale(std::locale::classic(), new CommaDecimal));
    const auto localized_candidates = numeric_candidates(1.249, 2);
    std::locale::global(previous_locale);
    assert((localized_candidates == std::vector<std::string>{"1.249","1.25","1.2","1"}));
    assert(round_decimal("2.675",2) == "2.68");
    assert(round_decimal("-2.675",2) == "-2.68");
    assert(round_decimal("-0.004",2) == "0");
    assert(round_decimal("9.99",0) == "10");
    assert(round_decimal("-9.5",0) == "-10");
    assert((numeric_candidates(24,6) == std::vector<std::string>{"24"}));
    assert(decimal_prediction(-0.0) == "0");
    assert(decimal_prediction(1e-8) == "0.00000001");
    assert(decimal_prediction(1e20) == "100000000000000000000");
    for (double number : {std::numeric_limits<double>::denorm_min(), std::numeric_limits<double>::max(), -1e-100}) {
        const auto candidates = numeric_candidates(number, 15);
        assert(candidates.size() <= 17);
        assert(candidates.front().find_first_of("eE") == std::string::npos);
        assert(numeric_value(candidates.front()) == number);
    }
    throws([] { numeric_candidates(std::numeric_limits<double>::infinity(), 6); });
}
