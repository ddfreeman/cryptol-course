# TODO
# - Add a function that would check stats prior to callees
#   --> Mention in the markdown file that this is referenced for preconditions
#   --> Relevant example: resolveAttack (integer overflow/underflow)
# - Try the alloc_pointsto_buffer example & see its limitations
# - Global variable
# - Extern
# - Field name (extra debug info)
# - Make a worksheet & solution for the SAW examples

# Done
# - Nested defines example (handled here...)
#   --> Mention in some SAW configs (i.e. llvm), this may be an issue
# - Aliasing / Memory Region disjoint example (selfDamage)
#   --> Mention in some SAW configs (i.e. llvm), this may be an issue

#######################################
# Imporant Imports
#######################################

import os
import unittest
from saw_client             import *
from saw_client.crucible    import * 
from saw_client.llvm        import * 
from saw_client.proofscript import *
from saw_client.llvm_type   import * 


#######################################
# Defines and Constants
#######################################

MAX_NAME_LENGTH = 12
SUCCESS         = 170
FAILURE         = 85
MAX_STAT        = 100
SCREEN_ROWS     = 15
SCREEN_COLS     = 10
SCREEN_TILES    = SCREEN_ROWS * SCREEN_COLS
NEUTRAL         = 0
DEFEAT_PLAYER   = 1
DEFEAT_OPPONENT = 2


#######################################
# SAW Helper Functions
#######################################

def ptr_to_fresh(spec: Contract, ty: LLVMType,
                 name: str) -> Tuple[FreshVar, SetupVal]:
  var = spec.fresh_var(ty, name)
  ptr = spec.alloc(ty, points_to = var)
  return (var, ptr)


#######################################
# SAW Contracts
#######################################

# levelUp Contract
# uint32_t levelUp(uint32_t level)
class levelUp_Contract(Contract):
  def specification (self):
    # Declare level variable
    level = self.fresh_var(i32, "level")

    # Symbolically execute the function
    self.execute_func(level)

    # Assert the function's return behavior
    self.returns_f("levelUp {level}")


# initDefaultPlayer Contract
# uint32_t initDefaultPlayer(player_t* player)
class initDefaultPlayer_Contract(Contract):
  def specification (self):
    # Pull the struct from the bitcode
    # Although the function uses player_t, pass character_t to SAW since
    # player_t is an alternative typedef name for character_t.
    player = self.alloc(alias_ty("struct.character_t"))

    self.execute_func(player)

    # Assert the post-condition behaviors
    # Note: The following explicit points_to method is currently the only way
    #       to assert struct field contents.
    # Index 0 = "name" field
    # Recall that 0x41 is ASCII for 'A'
    self.points_to(player[0], cry_f("[(i*0 + 0x41) | i <- [1..{MAX_NAME_LENGTH}]]"))

    # Index 1 is the "level" field
    self.points_to(player[1], cry_f("1 : [32]"))

    # Index 2 is the "hp" field
    self.points_to(player[2], cry_f("10 : [32]"))

    # Index 3 is the "atk" field
    self.points_to(player[3], cry_f("5 : [32]"))

    # Index 4 is the "def" field
    self.points_to(player[4], cry_f("4 : [32]"))

    # Index 5 is the "spd" field
    self.points_to(player[5], cry_f("3 : [32]"))

    # Incorrect Alternative 1: Invalid label in record update.
    #self.points_to(player, cry_f("{{ [(i*0 + 0x41) | i <- [1..{MAX_NAME_LENGTH}]], 1 : [32], 10 : [32], 5 : [32], 4 : [32], 3 : [32] }}"))

    # Incorrect Alternative 2: SAW doesn't yet support translating Cryptol's
    #                          record type(s) into crucible-llvm's type system.
    #self.points_to(player, cry_f("{{ name=[(i*0 + 0x41) | i <- [1..{MAX_NAME_LENGTH}]], level=1 : [32], hp=10 : [32], atk=5 : [32], def=4 : [32], spd=3 : [32] }}"))

    self.returns(cry_f("`({SUCCESS}) : [32]"))


# resolveAttack Contract
# void resolveAttack(character_t* target, uint32_t atk)
class resolveAttack_Contract(Contract):
  def __init__(self, case : int):
    super().__init__()
    self.case = case
    # There are 3 possible cases for resolveAttack
    #   Case 1: Attack mitigated
    #   Case 2: Immediate KO
    #   Case 3: Regular attack
    # Each case results in a different function behavior for calculating the
    # target's remaining HP. While we could make 3 separate contracts to handle
    # all of the possible cases, we can pass a parameter to the contract, which
    # identifies what preconditions and postconditions to set.

  def specification (self):
    # Declare variables
    (target, target_p) = ptr_to_fresh(self, alias_ty("struct.character_t"), name="target")
    atk = self.fresh_var(i32, "atk")

    # Assert the precondition that the stats are below the max stat cap
    # Pop Quiz: Why do we need these preconditions?
    self.precondition_f("{atk} <= `{MAX_STAT}")
    self.precondition_f("{target}.2 <= `{MAX_STAT}")
    self.precondition_f("{target}.4 <= `{MAX_STAT}")

    # Determine the preconditions based on the case parameter
    if (self.case == 1):
      # target->def >= atk
      self.precondition_f("{target}.4 >= {atk}")
    elif (self.case == 2):
      # target->hp <= (atk - target->def)
      self.precondition_f("({target}.2 + {target}.4) <= {atk}")
    else:
      # Assume any other case follows the formal attack calculation
      self.precondition_f("{target}.4 < {atk}")
      self.precondition_f("({target}.2 + {target}.4) > {atk}")
    
    # Symbolically execute the function
    self.execute_func(target_p, atk)

    # Determine the postcondition based on the case parameter
    if (self.case == 1):
      self.points_to(target_p[2], cry_f("{target}.2 : [32]"))
    elif (self.case == 2):
      self.points_to(target_p[2], cry_f("0 : [32]"))
    else:
      self.points_to(target_p[2], cry_f("resolveAttack ({target}.2) ({target}.4) {atk}"))

    self.returns(void)


# resetInventoryItems Contract
# void resetInventoryItems(inventory_t* inventory)
class resetInventoryItems_Contract(Contract):
  def __init__(self, numItems : int):
    super().__init__()
    self.numItems = numItems
    # Note: The inventory_t struct defines its item field as a item_t pointer.
    #       Instead of declaring a fixed array size, the pointer enables for a
    #       variable size depending on the memory allocation configured by its
    #       caller.
    #       While this is valid C syntax, SAW and Cryptol require the known
    #       size ahead of time. Here, our contract takes the numItems parameter
    #       to declare a fixed array size.

  def specification (self):
    # Declare variables
    (item, item_p) = ptr_to_fresh(self, array_ty(self.numItems, alias_ty("struct.item_t")), name="item")
    inventory_p = self.alloc(alias_ty("struct.inventory_t"), points_to = struct(item, cry_f("{self.numItems} : [32]")))

    # Symbolically execute the function
    self.execute_func(inventory_p)

    # Assert the postconditions
    for i in range(self.numItems):
      self.points_to(inventory_p[0][i][1], cry_f("0 : [32]"))

    self.returns(void)


# initScreen Contract
# uint32_t initScreen(screen_t* screen, uint8_t assetID)
class initScreen_Contract(Contract):
  def specification (self):
    # Declare variables
    screen = self.alloc(alias_ty("struct.screen_t"))
    assetID = self.fresh_var(i8, "assetID")

    # Symbolically execute the function
    self.execute_func(screen, assetID)

    # Assert the postcondition
    self.points_to(screen[0], cry_f("[(i*0 + {assetID}) | i <- [1..{SCREEN_TILES}]]"))

    self.returns(cry_f("`({SUCCESS}) : [32]"))


# quickBattle Contract
# void quickBattle(player_t* player, character_t* opponent)
class quickBattle_Contract(Contract):
  def specification (self):
    # Declare variables
    (player, player_p)     = ptr_to_fresh(self, alias_ty("struct.character_t"), name="player")
    (opponent, opponent_p) = ptr_to_fresh(self, alias_ty("struct.character_t"), name="opponent")
    # Pop Quiz: Why does allocating the pointers in the following way yield an
    #           error?
    #player = self.alloc(alias_ty("struct.character_t"))
    #opponent = self.alloc(alias_ty("struct.character_t"))

    # Assert the precondition that both HPs are greater than 0
    self.precondition_f("{player}.2   > 0")
    self.precondition_f("{opponent}.2 > 0")

    # Assert the precondition that character stats are below the max stat cap
    # Pop Quiz: Explain why the proof fails when the following preconditions
    #           are commented out.
    self.precondition_f("{player}.2   <= `{MAX_STAT}")
    self.precondition_f("{player}.3   <= `{MAX_STAT}")
    self.precondition_f("{player}.4   <= `{MAX_STAT}")
    self.precondition_f("{player}.5   <= `{MAX_STAT}")
    self.precondition_f("{opponent}.2 <= `{MAX_STAT}")
    self.precondition_f("{opponent}.3 <= `{MAX_STAT}")
    self.precondition_f("{opponent}.4 <= `{MAX_STAT}")
    self.precondition_f("{opponent}.5 <= `{MAX_STAT}")

    # Symbolically execute the function
    self.execute_func(player_p, opponent_p)

    # Assert the postcondition
    self.returns(void)


# selfDamage Contract
# uint32_t selfDamage(player_t* player)
class selfDamage_Contract(Contract):
  def __init__(self, case : int):
    super().__init__()
    self.case = case
    # There are 3 possible cases for resolveAttack
    #   Case 1: Attack mitigated
    #   Case 2: Immediate KO
    #   Case 3: Regular attack
    # Each case results in a different function behavior for calculating the
    # player's remaining HP. While we could make 3 separate contracts to handle
    # all of the possible cases, we can pass a parameter to the contract, which
    # identifies what preconditions and postconditions to set.

  def specification (self):
    # Declare variables
    (player, player_p) = ptr_to_fresh(self, alias_ty("struct.character_t"), name="player")

    # Assert the preconditions
    self.precondition_f("{player}.2 > 5")
    self.precondition_f("{player}.3 == 5")
    self.precondition_f("{player}.4 == 0")

    # Assert the precondition that character stats are below the max stat cap
    # Pop Quiz: Explain why the proof fails when the following preconditions
    #           are commented out.
    self.precondition_f("{player}.2   <= `{MAX_STAT}")
    self.precondition_f("{player}.3   <= `{MAX_STAT}")
    self.precondition_f("{player}.4   <= `{MAX_STAT}")
    self.precondition_f("{player}.5   <= `{MAX_STAT}")

    # Determine the preconditions based on the case parameter
    if (self.case == 1):
      # player->def >= player->atk
      self.precondition_f("{player}.4 >= {player}.3")
    elif (self.case == 2):
      # player->hp <= (player->atk - player->def)
      self.precondition_f("({player}.2 + {player}.4) <= {player}.3")
    else:
      # Assume any other case follows the formal attack calculation
      self.precondition_f("{player}.4 < {player}.3")
      self.precondition_f("({player}.2 + {player}.4) > {player}.3")

    # Symbolically execute the function
    self.execute_func(player_p, player_p)

    # Assert the postcondition
    if (self.case == 1):
      self.points_to(player_p[2], cry_f("{player}.2 : [32]"))
      self.returns(cry_f("`({NEUTRAL}) : [32]"))
    elif (self.case == 2):
      self.points_to(player_p[2], cry_f("0 : [32]"))
      self.returns(cry_f("`({DEFEAT_PLAYER}) : [32]"))
    else:
      self.points_to(player_p[2], cry_f("resolveAttack ({player}.2) ({player}.4) {player}.3"))
      self.returns(cry_f("`({NEUTRAL}) : [32]"))

#######################################


#######################################
# Unit Tests
#######################################

class GameTests(unittest.TestCase):
  def test_Game(self):
    connect(reset_server=True)
    if __name__ == "__main__": view(LogResults(verbose_failure=True))

    pwd = os.getcwd()
    bitcode_name = pwd + "/artifacts/Game.bc"
    cryptol_name = pwd + "/specs/Game.cry"

    cryptol_load_file(cryptol_name)
    module = llvm_load_module(bitcode_name)

    levelUp_result             = llvm_verify(module, 'levelUp', levelUp_Contract())
    initDefaultPlayer_result   = llvm_verify(module, 'initDefaultPlayer', initDefaultPlayer_Contract())
    resolveAttack_case1_result = llvm_verify(module, 'resolveAttack', resolveAttack_Contract(1))
    resolveAttack_case2_result = llvm_verify(module, 'resolveAttack', resolveAttack_Contract(2))
    resolveAttack_case3_result = llvm_verify(module, 'resolveAttack', resolveAttack_Contract(3))
    resetInventoryItems_result = llvm_verify(module, 'resetInventoryItems', resetInventoryItems_Contract(5))
    initScreen_result          = llvm_verify(module, 'initScreen', initScreen_Contract())
    quickBattle_result         = llvm_verify(module, 'quickBattle', quickBattle_Contract(), lemmas=[resolveAttack_case1_result, resolveAttack_case2_result, resolveAttack_case3_result])
    selfDamage_case1_result    = llvm_verify(module, 'selfDamage', selfDamage_Contract(1), lemmas=[resolveAttack_case1_result, resolveAttack_case2_result, resolveAttack_case3_result])
    selfDamage_case2_result    = llvm_verify(module, 'selfDamage', selfDamage_Contract(2), lemmas=[resolveAttack_case1_result, resolveAttack_case2_result, resolveAttack_case3_result])
    selfDamage_case3_result    = llvm_verify(module, 'selfDamage', selfDamage_Contract(3), lemmas=[resolveAttack_case1_result, resolveAttack_case2_result, resolveAttack_case3_result])

    self.assertIs(levelUp_result.is_success(), True)
    self.assertIs(initDefaultPlayer_result.is_success(), True)
    self.assertIs(resolveAttack_case1_result.is_success(), True)
    self.assertIs(resolveAttack_case2_result.is_success(), True)
    self.assertIs(resolveAttack_case3_result.is_success(), True)
    self.assertIs(resetInventoryItems_result.is_success(), True)
    self.assertIs(initScreen_result.is_success(), True)
    self.assertIs(quickBattle_result.is_success(), True)
    self.assertIs(selfDamage_case1_result.is_success(), True)
    self.assertIs(selfDamage_case2_result.is_success(), True)
    self.assertIs(selfDamage_case3_result.is_success(), True)

if __name__ == "__main__":
  unittest.main()

#######################################