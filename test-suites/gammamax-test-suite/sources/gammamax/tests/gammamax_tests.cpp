#include "gammamax/config.hpp"
#include "gammamax/gamma_max.hpp"
#include "gammamax/k_tails.hpp"
#include "gammamax/json_io.hpp"
#include "gammamax/ngram.hpp"
#include "gammamax/pta.hpp"
#include "gammamax/rsr.hpp"
#include "gammamax/state_merge.hpp"
#include <cassert>
#include <iostream>
#include <limits>

using namespace gammamax;
class SetOracle final : public Oracle {
public:
    explicit SetOracle(std::set<std::string> accepted) : accepted_(std::move(accepted)) {}
    bool accepts(std::string_view value) override { std::string text(value); calls.push_back(text); return accepted_.contains(text); }
    std::vector<std::string> calls;
private:
    std::set<std::string> accepted_;
};
int main() {
    auto pta=build_pta({"", "ab", "ac"},100);
    assert(pta.accepts("")); assert(pta.accepts("ab")); assert(!pta.accepts("a"));
    StateId a{}; assert(pta.transition(pta.start_state(),'a',a));
    auto k1=compute_k_signatures(pta,1);
    assert(!same_k_signature(pta,pta.start_state(),a,k1));
    StateId b{},c{}; assert(pta.transition(a,'b',b)); assert(pta.transition(a,'c',c));
    auto k2=compute_k_signatures(pta,2);
    assert(same_k_signature(pta,b,c,k2));
    auto k0=compute_k_signatures(pta,0);
    assert(same_k_signature(pta,pta.start_state(),b,k0));

    // Top-level signatures may agree while deterministic merge closure would
    // force deeper, incompatible classes together. Old gammaMax rejects that
    // complete merge, rather than checking only its red-blue endpoints.
    auto folding_pta=build_pta({"a0x","b0y"},100);
    StateId qa{},qb{};
    assert(folding_pta.transition(folding_pta.start_state(),'a',qa));
    assert(folding_pta.transition(folding_pta.start_state(),'b',qb));
    auto folding_signatures=compute_k_signatures(folding_pta,2);
    assert(same_k_signature(folding_pta,qa,qb,folding_signatures));
    auto incompatible=folding_pta; incompatible.merge_states(qa,qb);
    assert(!respects_k_signatures(incompatible,folding_signatures));
    NGramModel model({"aaaa","aaab"},2); assert(model.score("aaaa")>model.score("zzzz"));
    NGramModel disabled_model({"a"},0,"z");
    assert(disabled_model.score("anything")==0.0);

    // Start/end markers must not collide with any of the 256 byte symbols.
    const std::string control_bytes{"\x02\x03",2};
    NGramModel byte_model({control_bytes},2);
    assert(byte_model.score(control_bytes)>byte_model.score(std::string{"\x02\x02",2}));

    // The corrupt input contributes symbols to V but not observations.
    NGramModel training_vocabulary({"a"},1);
    NGramModel expanded_vocabulary({"a"},1,"z");
    assert(expanded_vocabulary.score("a")<training_vocabulary.score("a"));
    auto repair=rsr_repair(pta,"ad"); assert(repair);
    assert(repair->edit_distance==1); assert(repair->value=="ab" || repair->value=="ac");

    // Exact exclusion rejects only selected word. Prefixes, extensions, and
    // strings diverging from selected path preserve source behavior.
    auto exclusion_source=build_pta({"","a","ab","abc","ac","b"},100);
    auto without_ab=reject_exact_string(exclusion_source,"ab");
    for (const std::string value:{"","a","abc","ac","b"})
        assert(without_ab.accepts(value)==exclusion_source.accepts(value));
    assert(exclusion_source.accepts("ab")); assert(!without_ab.accepts("ab"));
    std::vector<std::string> exhaustive{""};
    for (std::size_t length=0;length<4;++length) {
        const auto prefixes=exhaustive;
        for (const auto& prefix:prefixes) {
            if (prefix.size()!=length) continue;
            for (char symbol:std::string{"abc"}) exhaustive.push_back(prefix+symbol);
        }
    }
    for (const auto& value:exhaustive)
        assert(without_ab.accepts(value)==
               (exclusion_source.accepts(value) && value!="ab"));
    auto without_ab_ac=reject_exact_string(without_ab,"ac");
    for (const auto& value:exhaustive)
        assert(without_ab_ac.accepts(value)==
               (exclusion_source.accepts(value) && value!="ab" && value!="ac"));
    auto without_empty=reject_exact_string(exclusion_source,"");
    assert(!without_empty.accepts("")); assert(without_empty.accepts("a"));
    auto unchanged=reject_exact_string(exclusion_source,"missing");
    for (const std::string value:{"","a","ab","abc","ac","b","missing"})
        assert(unchanged.accepts(value)==exclusion_source.accepts(value));
    auto repairs=rsr_repairs(pta,"ad",NGramModel({"ab"},2),2,1,20,10000);
    assert(repairs.size()==1);
    assert(repairs[0].value=="ab");
    assert(repairs[0].edit_distance==1);
    auto tiered=rsr_repairs(pta,"ad",NGramModel({"ab"},2),3,3,20,10000);
    assert(tiered.size()==3);
    std::set<std::string> tiered_values;
    for (const auto& candidate:tiered) tiered_values.insert(candidate.value);
    assert(tiered_values==std::set<std::string>({"","ab","ac"}));
    auto unseen=rsr_repairs(pta,"ad",NGramModel({"ab"},2),2,1,20,10000,{"ab"});
    assert(unseen.size()==1); assert(unseen.front().value!="ab");

    // Paper example: b(ab)* repaired from "bba" has minimum distance 2.
    Automaton cyclic;
    auto q0=cyclic.add_state(false), q1=cyclic.add_state(true),
         q2=cyclic.add_state(false);
    cyclic.set_start_state(q0);
    cyclic.state(q0).transitions.emplace('b',q1);
    cyclic.state(q1).transitions.emplace('a',q2);
    cyclic.state(q2).transitions.emplace('b',q1);
    auto paper_repair=rsr_repair(cyclic,"bba");
    assert(paper_repair);
    assert(paper_repair->edit_distance==2);
    assert(cyclic.accepts(paper_repair->value));
    auto merged=state_merge(pta,{"aa"},0); assert(!merged.automaton.accepts("aa"));
    // Learning keeps the PTA immutable and stores selected merges in a
    // lightweight partition. Materialization must preserve the quotient
    // language without modifying the base PTA.
    assert(pta.accepts("ab")); assert(!pta.accepts("aa"));
    auto rematerialized=merged.partition.materialize(pta);
    assert(rematerialized.accepts("ab")); assert(!rematerialized.accepts("aa"));

    // Speculative quotient merges must be exactly reversible, including
    // transitions, class metadata, and the constant-time evidence counter.
    PartitionedDfa transactional(pta);
    const auto original_fingerprint=transactional.materialize(pta).fingerprint();
    const auto original_accepting=transactional.accepting_class_count();
    const auto checkpoint=transactional.checkpoint();
    assert(transactional.merge_with_closure(pta,b,c,k2));
    assert(transactional.accepting_class_count()==original_accepting-1);
    transactional.rollback(checkpoint);
    assert(transactional.accepting_class_count()==original_accepting);
    assert(transactional.materialize(pta).fingerprint()==original_fingerprint);

    // EDSM ranks label agreement above incidental structural compression.
    // Merging q0-qA folds qX-qY too (two removed states), but joins no two
    // accepting classes. Merging q0-qB removes only qB, but has evidence 1.
    Automaton evidence_pta;
    auto e0=evidence_pta.add_state(true), eA=evidence_pta.add_state(false),
         eB=evidence_pta.add_state(true), eX=evidence_pta.add_state(false),
         eY=evidence_pta.add_state(false);
    evidence_pta.set_start_state(e0);
    evidence_pta.state(e0).transitions.emplace('a',eA);
    evidence_pta.state(e0).transitions.emplace('b',eB);
    evidence_pta.state(e0).transitions.emplace('x',eX);
    evidence_pta.state(eA).transitions.emplace('x',eY);
    auto structural_candidate=evidence_pta;
    structural_candidate.merge_states(e0,eA);
    auto labelled_candidate=evidence_pta;
    labelled_candidate.merge_states(e0,eB);
    assert(edsm_evidence(evidence_pta,structural_candidate)==0);
    assert(edsm_evidence(evidence_pta,labelled_candidate)==1);
    auto evidence_merge=state_merge(evidence_pta,{},0);
    assert(!evidence_merge.history.empty());
    assert(evidence_merge.history.front().blue_original_states==std::vector<StateId>{eB});

    auto input=parse_input_value(nlohmann::json{{"positive_examples",{"x"}},{"corrupt_string","y"}});
    assert(input.negative_examples.empty());
    auto config=parse_config_value(nlohmann::json{
        {"oracle",{{"executable","oracle"}}},{"state_merging",{{"k",0}}},
        {"repair",{{"n",2},{"rsr_batch_size",2},{"ngrams_batch_size",2},{"max_candidate_length",-1}}},
        {"limits",{{"max_iterations",8},{"max_total_oracle_calls",20},{"max_states",100},{"max_queue_size",-1}}}});
    assert(!config.seed); assert(config.rsr_batch_size==2);
    assert(config.ngrams_batch_size==2);
    assert(config.max_candidate_length==std::numeric_limits<std::size_t>::max());
    assert(config.max_queue_size==std::numeric_limits<std::size_t>::max());
    SetOracle oracle({"ab"});
    AlgorithmMeasurements measurements;
    assert(gamma_max(InputData{{"ab"},{},"ac"},config,oracle,&measurements)=="ab");
    assert(oracle.calls.front()=="ac");
    assert(measurements.total_iterations>=1);
    assert(measurements.edsm_execution_time_ns==
           measurements.initial_state_merge_ns+
           measurements.merge_replay_ns+
           measurements.resumed_state_merge_ns);
    auto measured_json=nlohmann::json::parse(serialize_result(
        ProgramResult{"ab",0,0,1,measurements}));
    assert(measured_json.at("total_iterations")==measurements.total_iterations);
    assert(measured_json.contains("rsr_execution_time_ns"));
    assert(measured_json.contains("initial_state_merge_ns"));
    assert(measured_json.contains("merge_replay_ns"));
    assert(measured_json.contains("resumed_state_merge_ns"));
    assert(measured_json.contains("candidate_copy_or_rollback_ns"));
    assert(measured_json.contains("negative_validation_ns"));
    SetOracle rejecting({});
    bool rejected_batch_failed=false;
    try { (void)gamma_max(InputData{{"ab","ac"},{},"ad"},config,rejecting); }
    catch (const std::runtime_error&) { rejected_batch_failed=true; }
    assert(rejected_batch_failed); assert(rejecting.calls.size()>=3);
    assert(rejecting.calls[0]=="ad");
    assert(rejecting.calls[1]!=rejecting.calls[2]);
    auto replay=replay_merges(pta,{"ab"},merged.history);
    assert(replay.automaton.accepts("ab"));
    std::cout << "ok\n";
}
