/* Tiny sparkline renderer. Looks for <span data-sparkline="v1,v2,..."></span>
 * and replaces innerText with a unicode block sparkline. Pure DOM; no deps. */
(function () {
  var blocks = ["▁","▂","▃","▄","▅","▆","▇","█"];
  var spans = document.querySelectorAll('[data-sparkline]');
  for (var i = 0; i < spans.length; i++) {
    var raw = spans[i].getAttribute('data-sparkline') || '';
    var nums = raw.split(',').map(function(x){return parseFloat(x)||0;});
    if (nums.length === 0) continue;
    var max = Math.max.apply(null, nums);
    var min = Math.min.apply(null, nums);
    var rng = (max - min) || 1;
    var out = '';
    for (var j = 0; j < nums.length; j++) {
      var idx = Math.floor(((nums[j]-min)/rng) * (blocks.length-1));
      out += blocks[Math.max(0, Math.min(blocks.length-1, idx))];
    }
    spans[i].textContent = out;
  }
})();
