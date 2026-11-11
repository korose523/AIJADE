const $entry = (() => {
  let $v_combinations_with_replacement;
  $v_combinations_with_replacement = $p.modules.itertools.combinations_with_replacement;
  function $v_combinations_colors($v_l, $v_n) {
    return $p.b.list(...[$v_combinations_with_replacement(...[$v_l, $v_n])]);
    return null;
  }
  return $v_combinations_colors;
})();
const solve = $p.wrap($entry, {"bigint":false,"tuples":false,"entries":false,"decimalDigits":false});
